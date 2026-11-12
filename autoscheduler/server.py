"""휴대폰 알림 전달 앱(MacroDroid/Tasker 등)이 호출하는 웹훅 서버."""
from __future__ import annotations

import hmac
import json
import logging
from datetime import datetime
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ValidationError

from .models import ChatMessage, Source
from .pipeline import Scheduler

log = logging.getLogger(__name__)

PACKAGE_TO_SOURCE: dict[str, Source] = {
    "com.kakao.talk": "kakao",
    "com.towneers.www": "daangn",  # 당근
}
NAME_TO_SOURCE: dict[str, Source] = {
    "kakao": "kakao", "kakaotalk": "kakao", "카카오톡": "kakao",
    "daangn": "daangn", "karrot": "daangn", "당근": "daangn", "당근마켓": "daangn",
}


class NotificationIn(BaseModel):
    app: str
    """패키지명(com.kakao.talk) 또는 앱 이름(카카오톡, 당근)"""
    title: str = ""
    """알림 제목. 카카오톡 1:1 은 보낸 사람, 당근은 상대 닉네임"""
    text: str
    """알림 본문 (메시지 내용)"""
    room: str | None = None
    """단톡방 이름 (카카오톡 그룹 알림의 subText/대화방 이름). 없으면 title 을 방 이름으로 사용"""
    sender: str | None = None
    timestamp: datetime | None = None


def resolve_source(app: str) -> Source:
    key = app.strip()
    if key in PACKAGE_TO_SOURCE:
        return PACKAGE_TO_SOURCE[key]
    return NAME_TO_SOURCE.get(key.lower(), "other")


def to_message(n: NotificationIn, tz) -> ChatMessage:
    source = resolve_source(n.app)
    room = (n.room or n.title or "알 수 없음").strip()
    sender = (n.sender or n.title or "상대").strip()
    text = n.text
    # 카카오톡 단톡방 알림은 본문이 '보낸사람: 내용' 형태로 오기도 한다
    if n.room and not n.sender and ": " in text:
        head, _, rest = text.partition(": ")
        if 0 < len(head) <= 20:
            sender, text = head.strip(), rest
    ts = n.timestamp or datetime.now(tz)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=tz)
    return ChatMessage(source, room, sender, text, ts.astimezone(tz))


def create_app(scheduler: Scheduler) -> FastAPI:
    app = FastAPI(title="Auto-scheduling")
    settings = scheduler.settings

    def check(token: str | None) -> None:
        if not settings.webhook_token:
            raise HTTPException(500, "AUTOSCHEDULER_WEBHOOK_TOKEN 이 설정되지 않았습니다")
        if not token or not hmac.compare_digest(token, settings.webhook_token):
            raise HTTPException(401, "invalid token")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "dry_run": settings.dry_run}

    @app.get("/usage")
    def usage(request: Request) -> dict:
        """토큰 사용량 (오늘 / 이번 달 / 전체). ?token=... 또는 X-Auth-Token 필요"""
        check(request.headers.get("x-auth-token") or request.query_params.get("token"))
        now = datetime.now(settings.tz)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        def summarize(rows):
            known = [u.cost_usd for u in rows if u.cost_usd is not None]
            return {
                "calls": sum(u.calls for u in rows),
                "input_tokens": sum(u.input_tokens for u in rows),
                "output_tokens": sum(u.output_tokens for u in rows),
                "cache_read_tokens": sum(u.cache_read_tokens for u in rows),
                "cache_write_tokens": sum(u.cache_write_tokens for u in rows),
                "estimated_cost_usd": round(sum(known), 6),
                "by_model": [{"model": u.model, "calls": u.calls, "input_tokens": u.input_tokens,
                              "output_tokens": u.output_tokens, "estimated_cost_usd": u.cost_usd}
                             for u in rows],
            }

        store = scheduler.store
        return {
            "today": summarize(store.usage_summary(since=today)),
            "this_month": summarize(store.usage_summary(since=today.replace(day=1))),
            "all_time": summarize(store.usage_summary()),
        }

    @app.post("/webhook/notification")
    async def notification(request: Request) -> dict:
        """JSON 본문, form-urlencoded 본문, URL 쿼리 파라미터 중 어느 방식으로 보내도 된다.
        (자동화 앱이 메시지 속 따옴표를 이스케이프하지 않아 JSON이 깨지는 경우 쿼리/폼 방식을 쓰면 안전)"""
        fields: dict[str, str] = dict(request.query_params)
        raw = (await request.body()).decode("utf-8", errors="replace").strip()
        if raw:
            ctype = request.headers.get("content-type", "")
            parsed: dict | None = None
            if "json" in ctype or raw.startswith("{"):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = None
            if parsed is None and "=" in raw:
                parsed = dict(parse_qsl(raw, keep_blank_values=True))
            if not isinstance(parsed, dict):
                raise HTTPException(400, "본문을 해석할 수 없습니다 (JSON 또는 form 형식)")
            fields.update({k: v for k, v in parsed.items() if v is not None})
        check(request.headers.get("x-auth-token") or fields.pop("token", None))
        fields.pop("token", None)
        try:
            payload = NotificationIn.model_validate({k: v for k, v in fields.items() if v != ""})
        except ValidationError as e:
            raise HTTPException(422, e.errors(include_url=False)) from e
        msg = to_message(payload, settings.tz)
        preview = msg.text if len(msg.text) <= 40 else msg.text[:40] + "…"
        log.info("알림 수신: 앱=%s(%s) 방=%s 보낸사람=%s 내용=%s",
                 payload.app, msg.source, msg.room, msg.sender, preview)
        if msg.source == "other":
            return {"ignored": f"지원하지 않는 앱: {payload.app}"}
        # Claude·캘린더 호출은 블로킹이므로 스레드에서 실행
        from starlette.concurrency import run_in_threadpool

        report = await run_in_threadpool(scheduler.handle_message, msg)
        if report.created or report.updated or report.cancelled:
            log.info("반영 결과: %s", report.as_dict())
        return report.as_dict()

    return app
