from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from .config import Settings


def _scheduler(settings: Settings):
    from .extractor import ClaudeExtractor
    from .gcal import DryRunCalendar, GoogleCalendar
    from .pipeline import Scheduler
    from .store import Store

    calendar = (
        DryRunCalendar() if settings.dry_run
        else GoogleCalendar(settings.credentials_file, settings.token_file, settings.calendar_id)
    )
    return Scheduler(settings, Store(settings.db_path), ClaudeExtractor(settings.model), calendar)


def cmd_auth(settings: Settings, args) -> None:
    from .gcal import authorize

    authorize(settings.credentials_file, settings.token_file, open_browser=not args.no_browser)
    print(f"구글 인증 완료 → {settings.token_file}")


def cmd_import(settings: Settings, args) -> None:
    from .parsers.kakao_export import parse_kakao_export_file

    messages = parse_kakao_export_file(Path(args.file), settings.tz, room=args.room)
    if not messages:
        sys.exit("메시지를 하나도 읽지 못했습니다. 카카오톡 '대화 내보내기' 텍스트 파일인지 확인하세요.")
    since = None
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=settings.tz)
    print(f"{len(messages)}개 메시지 읽음 (방: {messages[0].room})")
    report = _scheduler(settings).import_messages(messages, since=since)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))


def cmd_serve(settings: Settings, args) -> None:
    import uvicorn

    from .server import create_app

    if not settings.webhook_token:
        sys.exit(".env 에 AUTOSCHEDULER_WEBHOOK_TOKEN 을 설정하세요.")
    uvicorn.run(create_app(_scheduler(settings)), host=args.host, port=args.port)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="autoscheduler", description="채팅 → 구글 캘린더 자동 등록")
    parser.add_argument("--dry-run", action="store_true", help="캘린더에 쓰지 않고 결과만 출력")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("auth", help="구글 계정 로그인 (최초 1회)")
    p.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않고 URL만 출력")
    p.set_defaults(func=cmd_auth)

    p = sub.add_parser("import-kakao", help="카카오톡 대화 내보내기 파일에서 일정 등록")
    p.add_argument("file")
    p.add_argument("--room", help="채팅방 이름 (파일 첫 줄에서 자동 인식)")
    p.add_argument("--since", help="이 날짜 이후 메시지만 처리 (예: 2026-11-01)")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("serve", help="휴대폰 알림을 받는 웹훅 서버 실행")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    if args.dry_run:
        settings.dry_run = True
    args.func(settings, args)


if __name__ == "__main__":
    main()
