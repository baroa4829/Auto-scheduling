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
    store = Store(settings.db_path)
    extractor = ClaudeExtractor(
        settings.model,
        on_usage=lambda usage, source, room: store.record_usage(usage, source, room),
    )
    return Scheduler(settings, store, extractor, calendar)


def _print_usage(title: str, rows) -> None:
    print(f"\n[{title}]")
    if not rows:
        print("  Claude 호출 없음")
        return
    total_cost = 0.0
    unknown = False
    for u in rows:
        print("  " + u.describe())
        if u.cost_usd is None:
            unknown = True
        else:
            total_cost += u.cost_usd
    calls = sum(u.calls for u in rows)
    tokens = sum(u.total_tokens for u in rows)
    suffix = " (일부 모델 가격 제외)" if unknown else ""
    print(f"  합계: 호출 {calls}회, {tokens:,} 토큰, ≈ ${total_cost:.4f}{suffix}")


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
    started = datetime.now().astimezone()
    scheduler = _scheduler(settings)
    report = scheduler.import_messages(messages, since=since)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    _print_usage("이번 실행의 토큰 사용량", scheduler.store.usage_summary(since=started))


def cmd_usage(settings: Settings, args) -> None:
    from .store import Store

    store = Store(settings.db_path)
    now = datetime.now().astimezone()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    _print_usage(f"오늘 ({today:%Y-%m-%d})", store.usage_summary(since=today))
    _print_usage(f"이번 달 ({today:%Y-%m})", store.usage_summary(since=today.replace(day=1)))
    _print_usage("전체", store.usage_summary())
    print("\n※ 비용은 토큰 수 × 공개 단가로 계산한 추정치입니다. 정확한 청구액은 console.anthropic.com 에서 확인하세요.")


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

    p = sub.add_parser("usage", help="Claude API 토큰 사용량·추정 비용 보기")
    p.set_defaults(func=cmd_usage)

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
