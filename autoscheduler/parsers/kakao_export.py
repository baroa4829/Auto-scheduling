"""카카오톡 '대화 내보내기' 텍스트 파일 파서.

지원 형식
- 안드로이드:  2026년 11월 5일 오후 3:21, 홍길동 : 메시지
- iOS:        2026. 11. 5. 오후 3:21, 홍길동 : 메시지   (24시간제 15:21 도 허용)
- PC(Windows): --------------- 2026년 11월 5일 목요일 ---------------
               [홍길동] [오후 3:21] 메시지
여러 줄 메시지는 이전 메시지에 이어 붙인다.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..models import ChatMessage

_AMPM = r"(?:(?P<ampm>오전|오후|AM|PM|am|pm)\s*)?"

_MOBILE = re.compile(
    r"^(?P<y>\d{4})(?:년|\.)\s*(?P<m>\d{1,2})(?:월|\.)\s*(?P<d>\d{1,2})(?:일|\.)?\s*,?\s*"
    + _AMPM
    + r"(?P<h>\d{1,2}):(?P<mi>\d{2})\s*,\s*(?P<sender>[^:]+?)\s*:\s?(?P<text>.*)$"
)
_PC_DATE = re.compile(r"^-+\s*(?P<y>\d{4})년\s*(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일.*-+\s*$")
_PC_MSG = re.compile(r"^\[(?P<sender>[^\]]+)\]\s*\[" + _AMPM + r"(?P<h>\d{1,2}):(?P<mi>\d{2})\]\s?(?P<text>.*)$")
_TITLE = re.compile(r"^(?P<room>.+?)\s*(?:님과)?\s*카카오톡 대화\s*$")
# 대화 내용이 아닌 시스템 줄 (날짜 구분선, 입장/퇴장 안내 등)
_MOBILE_DATE_ONLY = re.compile(r"^\d{4}(?:년|\.)\s*\d{1,2}(?:월|\.)\s*\d{1,2}(?:일|\.)?\s*\S*요일\s*$")
_SYSTEM_AFTER_TIME = re.compile(r"^\d{4}(?:년|\.)\s*\d{1,2}(?:월|\.)\s*\d{1,2}(?:일|\.)?\s*,?\s*" + _AMPM + r"\d{1,2}:\d{2}\s*[,:]?\s*[^:]*$")


def _hour24(hour: int, ampm: str | None) -> int:
    if not ampm:
        return hour
    pm = ampm.lower() in {"오후", "pm"}
    if pm and hour < 12:
        return hour + 12
    if not pm and hour == 12:
        return 0
    return hour


def parse_kakao_export(
    text: str, tz: ZoneInfo, room: str | None = None
) -> list[ChatMessage]:
    lines = text.lstrip("﻿").splitlines()
    if room is None:
        room = "카카오톡"
        for line in lines[:3]:
            m = _TITLE.match(line.strip())
            if m:
                room = m.group("room").strip()
                break

    messages: list[ChatMessage] = []
    current_day: date | None = None
    header_done = False

    for raw in lines:
        line = raw.rstrip("\r")
        stripped = line.strip()

        m = _MOBILE.match(stripped)
        if m:
            header_done = True
            ts = datetime(
                int(m["y"]), int(m["m"]), int(m["d"]),
                _hour24(int(m["h"]), m["ampm"]), int(m["mi"]), tzinfo=tz,
            )
            messages.append(ChatMessage("kakao", room, m["sender"].strip(), m["text"], ts))
            continue

        m = _PC_DATE.match(stripped)
        if m:
            header_done = True
            current_day = date(int(m["y"]), int(m["m"]), int(m["d"]))
            continue

        m = _PC_MSG.match(stripped)
        if m and current_day is not None:
            ts = datetime(
                current_day.year, current_day.month, current_day.day,
                _hour24(int(m["h"]), m["ampm"]), int(m["mi"]), tzinfo=tz,
            )
            messages.append(ChatMessage("kakao", room, m["sender"].strip(), m["text"], ts))
            continue

        if _MOBILE_DATE_ONLY.match(stripped) or _SYSTEM_AFTER_TIME.match(stripped):
            header_done = True
            continue

        # 여러 줄 메시지의 이어지는 줄
        if header_done and messages and stripped:
            messages[-1].text += "\n" + line

    return messages


def parse_kakao_export_file(path: Path, tz: ZoneInfo, room: str | None = None) -> list[ChatMessage]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    return parse_kakao_export(text, tz, room)
