"""데일리 브리핑 봇 진입점.

하루 일정 (KST):
    07:30 weather --edition morning  오늘의 날씨
    08시  news --edition morning     1차 뉴스 브리핑
    12시  news --edition noon        2차 뉴스 브리핑
    16시  news --edition afternoon   3차 뉴스 브리핑
    17시  weather --edition evening  저녁 날씨 & 내일 예보
    22시  news --edition evening     하루 마무리 뉴스 브리핑

증시 리포트 (KST, 거래일만):
    08:30 stock --edition morning    간밤 미국 증시 + 환율·원자재 + 관심 종목 (화~토)
    16:10 stock --edition close      국내 증시 마감 + 아시아 + 관심 종목 (월~금)

사용 예:
    python -m briefing_bot.main weather
    python -m briefing_bot.main news --edition noon
    python -m briefing_bot.main news --edition evening --sections pol,eco --no-send
    python -m briefing_bot.main stock --edition close --no-send
    python -m briefing_bot.main auto            # 현재 KST 시각에 맞는 작업 실행
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from . import notifier, scraper, stocks, summarizer, weather

KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class Edition:
    key: str
    order: int  # 같은 날 브리핑 순서 (🆕 비교용)
    hour: int  # 예정 시각 (KST)
    title: str
    tone: str = ""


EDITIONS: dict[str, Edition] = {
    e.key: e
    for e in [
        Edition("morning", 1, 8, "🌅 1차 뉴스 브리핑",
                "이번 브리핑은 아침 출근길용입니다. headline 은 오늘 아침 주목할 흐름으로 씁니다."),
        Edition("noon", 2, 12, "☀️ 2차 뉴스 브리핑",
                "이번 브리핑은 점심 시간용입니다. headline 은 오전 동안의 흐름으로 씁니다."),
        Edition("afternoon", 3, 16, "🌇 3차 뉴스 브리핑",
                "이번 브리핑은 오후용입니다. headline 은 오후까지의 흐름으로 씁니다."),
        Edition("evening", 4, 22, "🌙 하루 마무리 뉴스 브리핑",
                "이번 브리핑은 하루를 마무리하는 밤 브리핑입니다. headline 은 이 분야의 오늘 하루를 정리하는 문장으로 씁니다."),
    ]
}

URL_RE = re.compile(r"\((https://news\.nate\.com/view/[^)\s]+)\)")


def now_kst() -> datetime:
    return datetime.now(KST)


def _write_outputs(path: Path, markdown: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    logging.info("저장: %s", path)
    if summary_file := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(markdown)


def _send(markdown: str, telegram: list[str], no_send: bool) -> None:
    if no_send:
        print(markdown)
        return
    sent = notifier.dispatch(markdown, telegram)
    logging.info("전송 완료: %s", sent)


# ---------------- 날씨 ----------------

def _already_sent(path: Path, force: bool) -> bool:
    """같은 날 같은 브리핑이 이미 나갔으면 True (예약 실행 지연 + 수동 실행 중복 방지)."""
    if path.exists() and not force:
        logging.info("이미 보낸 브리핑이라 건너뜁니다: %s (다시 보내려면 --force)", path)
        return True
    return False


def run_weather(args: argparse.Namespace) -> int:
    day = now_kst().date()
    out_path = Path(args.out_dir) / f"{day:%Y-%m-%d}" / f"weather-{args.edition}.md"
    if _already_sent(out_path, args.force):
        return 0
    if not check_secrets(False, not args.no_send):
        return 1
    markdown, telegram = weather.build(day, args.edition)
    _write_outputs(out_path, markdown)
    _send(markdown, telegram, args.no_send)
    return 0


# ---------------- 증시 ----------------

def run_stock(args: argparse.Namespace) -> int:
    day = now_kst().date()
    out_path = Path(args.out_dir) / f"{day:%Y-%m-%d}" / f"stock-{args.edition}.md"
    if _already_sent(out_path, args.force):
        return 0
    if not check_secrets(not args.no_summary, not args.no_send):
        return 1

    watchlist = stocks.parse_watchlist(args.watchlist)
    quotes = stocks.collect(args.edition, watchlist)
    if not any(quotes.values()):
        logging.error("시세를 하나도 가져오지 못했습니다.")
        return 1
    if not args.force and not stocks.is_market_day(args.edition, day, quotes):
        logging.info("휴장일이라 증시 리포트를 건너뜁니다 (보내려면 --force)")
        return 0

    comment = None
    if not args.no_summary:
        comment = stocks.market_comment(args.edition, quotes, stocks.economy_headlines(day))
    markdown = stocks.render_markdown(args.edition, day, quotes, comment)
    telegram = stocks.render_telegram(args.edition, day, quotes, comment)
    _write_outputs(out_path, markdown)
    _send(markdown, telegram, args.no_send)
    return 0


# ---------------- 뉴스 ----------------

def _previous_urls(day_dir: Path, edition: Edition) -> set[str] | None:
    """같은 날 앞선 브리핑에 나온 기사 URL. 앞선 브리핑이 없으면 None (🆕 표시 안 함)."""
    urls: set[str] = set()
    found = False
    for e in EDITIONS.values():
        if e.order >= edition.order:
            continue
        f = day_dir / f"{e.order}-{e.key}.md"
        if f.exists():
            found = True
            urls |= set(URL_RE.findall(f.read_text(encoding="utf-8")))
    return urls if found else None


def check_secrets(need_claude: bool, need_telegram: bool) -> bool:
    missing = []
    if need_claude and not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    if need_telegram:
        missing += [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.environ.get(k)]
    if missing:
        logging.error(
            "필요한 Secret 이 비어 있습니다: %s — GitHub 저장소 Settings → Secrets and variables → "
            "Actions → 'Repository secrets' 에 정확한 이름으로 등록했는지 확인하세요.",
            ", ".join(missing),
        )
        return False
    return True


def run_news(args: argparse.Namespace) -> int:
    edition = EDITIONS[args.edition]
    today = now_kst().date()
    day = datetime.strptime(args.date, "%Y%m%d").date() if args.date else today
    if _already_sent(Path(args.out_dir) / f"{day:%Y-%m-%d}" / f"{edition.order}-{edition.key}.md", args.force):
        return 0
    if not check_secrets(not args.no_summary, not args.no_send):
        return 1

    codes = [c.strip() for c in args.sections.split(",") if c.strip()]
    unknown = [c for c in codes if c not in scraper.SECTIONS]
    if unknown:
        logging.error("알 수 없는 분야 코드: %s", unknown)
        return 2
    sections = {c: scraper.SECTIONS[c] for c in codes}

    # 1) 랭킹(제목)만 먼저 모은다. 본문은 분야 선택이 끝난 뒤 한 번만 가져온다.
    session = requests.Session()
    collected = scraper.collect_rankings(session, sections, day, args.top)

    # 이른 아침에는 오늘 랭킹이 아직 쌓이지 않았을 수 있어 어제 랭킹으로 보충
    notes: list[str] = []
    if not args.date:
        thin = {c: n for c, n in sections.items() if len(collected.get(n, [])) < args.top}
        if thin:
            prev = day - timedelta(days=1)
            refill = scraper.collect_rankings(session, thin, prev, args.top)
            for name, arts in refill.items():
                if len(arts) > len(collected.get(name, [])):
                    collected[name] = arts
                    notes.append(f"{name}: 오늘 랭킹이 아직 부족해 어제({prev:%m/%d}) 랭킹을 사용했습니다")

    # 2) 본문 수집 (실패해도 제목만으로 요약 진행)
    scraper.fetch_bodies(session, collected)
    session.close()

    if not any(collected.values()):
        logging.error("수집된 기사가 없습니다. 네이트 페이지 구조가 바뀌었는지 확인하세요.")
        return 1

    summaries = {} if args.no_summary else summarizer.summarize_all(collected, edition.tone)
    overview = (
        summarizer.summarize_overview(collected, summaries)
        if edition.key == "evening" and not args.no_summary
        else None
    )

    day_dir = Path(args.out_dir) / f"{day:%Y-%m-%d}"
    prev_urls = _previous_urls(day_dir, edition)
    new_urls = (
        {a.url for arts in collected.values() for a in arts} - prev_urls
        if prev_urls is not None
        else set()
    )

    render_args = (edition.title, day, collected, summaries, new_urls, overview, notes)
    markdown = notifier.render_news_markdown(*render_args)
    telegram = notifier.render_news_telegram(*render_args)

    _write_outputs(day_dir / f"{edition.order}-{edition.key}.md", markdown)
    _send(markdown, telegram, args.no_send)
    return 0


# ---------------- 자동 선택 ----------------

WEATHER_TIMES = {"morning": (7, 30), "evening": (17, 0)}
STOCK_TIMES = {"morning": (8, 30), "close": (16, 10)}


def pick_task(now: datetime) -> tuple[str, str]:
    """현재 시각에서 가장 가까운 예정 작업을 고른다 (스케줄러 지연 ±90분 허용)."""
    slots = [("weather", k, h * 60 + m) for k, (h, m) in WEATHER_TIMES.items()] + [
        ("news", e.key, e.hour * 60) for e in EDITIONS.values()
    ] + [("stock", k, h * 60 + m) for k, (h, m) in STOCK_TIMES.items()]
    minutes = now.hour * 60 + now.minute
    best = min(slots, key=lambda s: abs(s[2] - minutes))
    if abs(best[2] - minutes) > 90:
        raise SystemExit(f"{now:%H:%M} 근처에 예정된 작업이 없습니다")
    return best[0], best[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="네이트 뉴스 + 날씨 데일리 브리핑 봇")
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--no-send", action="store_true", help="메신저 전송 없이 출력만")
    common.add_argument("--force", action="store_true", help="이미 보낸 브리핑이어도 다시 보냄")
    common.add_argument("--out-dir", default=os.environ.get("BRIEFING_OUT_DIR", "briefings"))

    wx = sub.add_parser("weather", parents=[common], help="날씨 (morning: 07:30 오늘 날씨, evening: 17시 저녁·내일 날씨)")
    wx.add_argument("--edition", choices=list(WEATHER_TIMES), default="morning")

    news = sub.add_parser("news", parents=[common], help="뉴스 브리핑")
    news.add_argument("--edition", choices=list(EDITIONS), default="morning")
    news.add_argument("--date", help="랭킹 기준일 YYYYMMDD (기본: 오늘 KST)")
    news.add_argument(
        "--sections",
        default=os.environ.get("NATE_SECTIONS") or ",".join(scraper.SECTIONS),
        help=f"분야 코드 쉼표 구분. 가능: {','.join(f'{k}({v})' for k, v in scraper.SECTIONS.items())}",
    )
    news.add_argument("--top", type=int, default=int(os.environ.get("TOP_N", 10)))
    news.add_argument("--no-summary", action="store_true", help="Claude 요약 없이 제목만")

    st = sub.add_parser("stock", parents=[common], help="증시 리포트 (morning: 08:30 미국장 정리, close: 16:10 국내장 마감)")
    st.add_argument("--edition", choices=list(STOCK_TIMES), default="close")
    st.add_argument("--watchlist", help="관심 종목 '이름:심볼,...' (기본: STOCK_WATCHLIST 변수)")
    st.add_argument("--no-summary", action="store_true", help="Claude 시장 코멘트 없이 시세만")

    sub.add_parser("auto", parents=[common], help="현재 시각에 맞는 작업 자동 실행")
    sub.add_parser("telegram-check", help="텔레그램 봇 토큰/채팅 ID 설정 진단")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)

    if args.cmd == "auto":
        cmd, edition = pick_task(now_kst())
        logging.info("자동 선택: %s %s", cmd, edition or "")
        extra = ["--no-send"] if args.no_send else []
        argv2 = [cmd] + (["--edition", edition] if edition else []) + extra
        args = parse_args(argv2)

    if args.cmd == "telegram-check":
        if not check_secrets(False, True):
            return 1
        return notifier.telegram_check(
            os.environ["TELEGRAM_BOT_TOKEN"].strip(), os.environ["TELEGRAM_CHAT_ID"]
        )
    if args.cmd == "weather":
        return run_weather(args)
    if args.cmd == "stock":
        return run_stock(args)
    return run_news(args)


if __name__ == "__main__":
    sys.exit(main())
