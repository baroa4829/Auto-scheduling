"""구글 캘린더 연동 (OAuth 데스크톱 앱 방식)."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


class CalendarClient(Protocol):
    def create(self, body: dict) -> str: ...
    def update(self, event_id: str, body: dict) -> None: ...


def authorize(credentials_file: Path, token_file: Path, open_browser: bool = True):
    """token.json 이 없거나 만료됐으면 브라우저 로그인으로 새로 발급한다."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not credentials_file.exists():
            raise FileNotFoundError(
                f"{credentials_file} 가 없습니다. README의 '구글 캘린더 API 준비'를 따라 내려받으세요."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
        creds = flow.run_local_server(port=8765, open_browser=open_browser)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


class GoogleCalendar:
    def __init__(self, credentials_file: Path, token_file: Path, calendar_id: str = "primary"):
        from googleapiclient.discovery import build

        creds = authorize(credentials_file, token_file)
        self.service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self.calendar_id = calendar_id

    def create(self, body: dict) -> str:
        created = self.service.events().insert(calendarId=self.calendar_id, body=body).execute()
        return created["id"]

    def update(self, event_id: str, body: dict) -> None:
        self.service.events().patch(calendarId=self.calendar_id, eventId=event_id, body=body).execute()


class DryRunCalendar:
    """실제로 쓰지 않고 로그만 남기는 캘린더 (테스트용)."""

    def __init__(self) -> None:
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []

    def create(self, body: dict) -> str:
        self.created.append(body)
        log.info("[DRY-RUN] 생성: %s", body)
        return f"dry-{len(self.created)}"

    def update(self, event_id: str, body: dict) -> None:
        self.updated.append((event_id, body))
        log.info("[DRY-RUN] 수정 %s: %s", event_id, body)


def build_event_body(
    title: str, start: str, end: str | None, all_day: bool, location: str | None,
    description: str, timezone: str, default_minutes: int = 60,
) -> dict:
    body: dict = {"summary": title, "description": description}
    if location:
        body["location"] = location
    if all_day:
        d = date.fromisoformat(start[:10])
        e = date.fromisoformat(end[:10]) if end else d
        # 구글 캘린더 종일 일정의 end 는 '다음 날'(exclusive)
        body["start"] = {"date": d.isoformat()}
        body["end"] = {"date": (max(e, d) + timedelta(days=1)).isoformat()}
    else:
        s = datetime.fromisoformat(start).replace(tzinfo=None)
        en = datetime.fromisoformat(end).replace(tzinfo=None) if end else None
        if en is None or en <= s:
            en = s + timedelta(minutes=default_minutes)
        body["start"] = {"dateTime": s.isoformat(timespec="minutes") + ":00", "timeZone": timezone}
        body["end"] = {"dateTime": en.isoformat(timespec="minutes") + ":00", "timeZone": timezone}
    return body
