from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["kakao", "daangn", "other"]


@dataclass
class ChatMessage:
    source: Source
    room: str
    sender: str
    text: str
    timestamp: datetime  # timezone-aware

    @property
    def fingerprint(self) -> str:
        raw = f"{self.source}|{self.room}|{self.sender}|{self.timestamp.isoformat()}|{self.text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class EventAction(BaseModel):
    """Claude가 대화에서 찾아낸 일정 하나에 대한 처리 지시."""

    action: Literal["create", "update", "cancel"] = Field(
        description="새 약속이면 create, 이미 등록된 약속의 시간·장소가 바뀌었으면 update, 취소됐으면 cancel"
    )
    existing_event_id: str | None = Field(
        default=None,
        description="update/cancel일 때 '이미 등록된 일정' 목록의 id. create면 null",
    )
    title: str = Field(description="캘린더에 표시할 짧은 제목. 예: '민수와 저녁', '당근 거래: 아이패드'")
    start: str = Field(description="시작 시각, ISO 8601 현지 시각 (예: 2026-11-13T19:00). 종일 일정은 2026-11-13")
    end: str | None = Field(default=None, description="종료 시각. 언급이 없으면 null")
    all_day: bool = Field(description="시각 없이 날짜만 정해졌으면 true")
    location: str | None = Field(default=None, description="장소. 없으면 null")
    status: Literal["confirmed", "tentative"] = Field(
        description="양쪽이 동의했으면 confirmed, 제안만 되고 답이 없으면 tentative"
    )
    evidence: str = Field(description="근거가 된 메시지를 짧게 인용")


class ExtractionResult(BaseModel):
    events: list[EventAction]
