"""메시지 → (Claude) 일정 추출 → 구글 캘린더 반영."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Sequence

from .config import Settings
from .extractor import Extractor, looks_like_schedule
from .gcal import CalendarClient, build_event_body
from .models import ChatMessage, EventAction
from .store import Store

log = logging.getLogger(__name__)

SOURCE_LABELS = {"kakao": "카카오톡", "daangn": "당근", "other": "메신저"}
TENTATIVE_PREFIX = "[미정] "
CANCELLED_PREFIX = "[취소] "


@dataclass
class ApplyReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def merge(self, other: "ApplyReport") -> None:
        for name in ("created", "updated", "cancelled", "skipped"):
            getattr(self, name).extend(getattr(other, name))

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("created", "updated", "cancelled", "skipped")}


class Scheduler:
    def __init__(self, settings: Settings, store: Store, extractor: Extractor, calendar: CalendarClient):
        self.settings = settings
        self.store = store
        self.extractor = extractor
        self.calendar = calendar

    # ---- 실시간 알림 한 건 ----
    def handle_message(self, msg: ChatMessage) -> ApplyReport:
        if not self.store.add_message(msg):
            return ApplyReport(skipped=["중복 메시지"])
        if not looks_like_schedule(msg.text):
            return ApplyReport()
        context = self.store.recent_messages(
            msg.source, msg.room, msg.timestamp,
            self.settings.context_messages, self.settings.context_hours,
        )
        return self._run(msg.source, msg.room, context)

    # ---- 내보내기 파일 일괄 처리 ----
    def import_messages(
        self, messages: Iterable[ChatMessage], since: datetime | None = None, chunk_size: int = 150,
    ) -> ApplyReport:
        report = ApplyReport()
        msgs = [m for m in messages if since is None or m.timestamp >= since]
        for m in msgs:
            self.store.add_message(m)
        by_room: dict[tuple[str, str], list[ChatMessage]] = {}
        for m in msgs:
            by_room.setdefault((m.source, m.room), []).append(m)
        for (source, room), room_msgs in by_room.items():
            room_msgs.sort(key=lambda m: m.timestamp)
            overlap = 10  # 청크 경계에서 끊긴 대화를 위해 앞부분을 겹쳐 보낸다
            start = 0
            while start < len(room_msgs):
                chunk = room_msgs[max(0, start - overlap): start + chunk_size]
                if any(looks_like_schedule(m.text) for m in chunk):
                    report.merge(self._run(source, room, chunk))
                start += chunk_size
        return report

    # ---- 공통 ----
    def _run(self, source: str, room: str, context: Sequence[ChatMessage]) -> ApplyReport:
        existing = self.store.active_events(source, room)
        result = self.extractor.extract(context, existing, SOURCE_LABELS.get(source, source), room)
        report = ApplyReport()
        for action in result.events:
            try:
                self._apply(source, room, action, report)
            except Exception:  # 한 건 실패가 나머지를 막지 않도록
                log.exception("일정 반영 실패: %s", action)
                report.skipped.append(f"오류: {action.title}")
        return report

    def _description(self, source: str, room: str, action: EventAction) -> str:
        return (
            f"{SOURCE_LABELS.get(source, source)} '{room}' 대화에서 자동 등록\n"
            f"근거: {action.evidence}\n\n(autoscheduler)"
        )

    def _title(self, action: EventAction) -> str:
        return (TENTATIVE_PREFIX + action.title) if action.status == "tentative" else action.title

    def _apply(self, source: str, room: str, action: EventAction, report: ApplyReport) -> None:
        tz = self.settings.timezone
        if action.action in ("update", "cancel"):
            stored = None
            if action.existing_event_id and action.existing_event_id.strip().isdigit():
                stored = self.store.get_event(int(action.existing_event_id))
            if stored is None or stored.room != room or stored.source != source or stored.cancelled:
                report.skipped.append(f"대상 일정 없음({action.action}): {action.title}")
                return
            if action.action == "cancel":
                if stored.gcal_id:
                    self.calendar.update(stored.gcal_id, {"summary": CANCELLED_PREFIX + stored.title,
                                                          "transparency": "transparent"})
                self.store.update_event(stored.id, cancelled=True)
                report.cancelled.append(stored.title)
                return
            # update
            if action.status == "tentative" and not self.settings.include_tentative:
                if stored.status == "confirmed":
                    report.skipped.append(f"미확정 변경 제안 무시: {action.title}")
                else:  # 아직 미확정 → 캘린더에는 쓰지 않고 기록만 갱신
                    self.store.update_event(stored.id, title=action.title, start=action.start,
                                            end=action.end, all_day=action.all_day,
                                            location=action.location)
                    report.skipped.append(f"미확정: {action.title} ({action.start})")
                return
            body = build_event_body(self._title(action), action.start, action.end, action.all_day,
                                    action.location, self._description(source, room, action), tz)
            if stored.gcal_id:
                self.calendar.update(stored.gcal_id, body)
            else:
                stored_gcal = self.calendar.create(body)
                self.store.update_event(stored.id, gcal_id=stored_gcal)
            self.store.update_event(stored.id, title=action.title, start=action.start, end=action.end,
                                    all_day=action.all_day, location=action.location, status=action.status)
            report.updated.append(f"{action.title} → {action.start}")
            return

        # create
        dup = self.store.find_duplicate(source, room, action.start)
        if dup is not None:
            writable = action.status == "confirmed" or self.settings.include_tentative
            if dup.gcal_id is None and writable:
                # 미확정으로 기록만 해 둔 약속이 확정됨 → 이제 캘린더에 등록
                body = build_event_body(self._title(action), action.start, action.end, action.all_day,
                                        action.location, self._description(source, room, action), tz)
                gcal_id = self.calendar.create(body)
                self.store.update_event(dup.id, gcal_id=gcal_id, status=action.status, title=action.title,
                                        end=action.end, location=action.location)
                report.created.append(f"{self._title(action)} ({action.start})")
            else:
                report.skipped.append(f"이미 등록됨: {action.title} ({action.start})")
            return
        if action.status == "tentative" and not self.settings.include_tentative:
            report.skipped.append(f"미확정: {action.title} ({action.start})")
            # 미확정이어도 기록해 두면 나중에 확정될 때 update 로 이어진다
            self.store.insert_event(source, room, action.title, action.start, action.end,
                                    action.all_day, action.location, "tentative", None)
            return
        body = build_event_body(self._title(action), action.start, action.end, action.all_day,
                                action.location, self._description(source, room, action), tz)
        gcal_id = self.calendar.create(body)
        self.store.insert_event(source, room, action.title, action.start, action.end,
                                action.all_day, action.location, action.status, gcal_id)
        report.created.append(f"{self._title(action)} ({action.start})")
