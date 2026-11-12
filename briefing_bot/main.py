"""네이트 뉴스 분야별 Top10 요약 브리핑 봇 진입점.

사용 예:
    python -m briefing_bot.main                    # 어제자 랭킹, 전 분야
    python -m briefing_bot.main --date 20261111    # 특정 날짜
    python -m briefing_bot.main --sections pol,eco --no-send
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import notifier, scraper, summarizer

KST = timezone(timedelta(hours=9))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="네이트 뉴스 분야별 Top10 브리핑 봇")
    p.add_argument(
        "--date",
        help="랭킹 기준일 YYYYMMDD (기본: 오늘 KST. 아침 실행이면 --yesterday 권장)",
    )
    p.add_argument("--yesterday", action="store_true", help="어제(KST) 랭킹 사용")
    p.add_argument(
        "--sections",
        default=os.environ.get("NATE_SECTIONS", ",".join(scraper.SECTIONS)),
        help=f"분야 코드 쉼표 구분. 가능: {','.join(f'{k}({v})' for k, v in scraper.SECTIONS.items())}",
    )
    p.add_argument("--top", type=int, default=int(os.environ.get("TOP_N", 10)))
    p.add_argument("--out-dir", default=os.environ.get("BRIEFING_OUT_DIR", "briefings"))
    p.add_argument("--no-send", action="store_true", help="메신저 전송 없이 파일만 저장")
    p.add_argument("--no-summary", action="store_true", help="Claude 요약 없이 제목만")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)

    today = datetime.now(KST).date()
    if args.date:
        day = datetime.strptime(args.date, "%Y%m%d").date()
    elif args.yesterday:
        day = today - timedelta(days=1)
    else:
        day = today

    codes = [c.strip() for c in args.sections.split(",") if c.strip()]
    unknown = [c for c in codes if c not in scraper.SECTIONS]
    if unknown:
        logging.error("알 수 없는 분야 코드: %s", unknown)
        return 2
    sections = {c: scraper.SECTIONS[c] for c in codes}

    collected = scraper.collect(sections, day, args.top)
    if not any(collected.values()):
        logging.error("수집된 기사가 없습니다. 네이트 페이지 구조가 바뀌었는지 확인하세요.")
        return 1

    summaries = {} if args.no_summary else summarizer.summarize_all(collected)
    markdown = notifier.render_markdown(day, collected, summaries)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{day:%Y-%m-%d}.md"
    out_path.write_text(markdown, encoding="utf-8")
    logging.info("브리핑 저장: %s", out_path)

    # GitHub Actions 실행 요약 페이지에도 표시
    if summary_file := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(markdown)

    if not args.no_send:
        sent = notifier.dispatch(day, collected, summaries, markdown)
        logging.info("전송 채널: %s", sent or "없음 (환경변수 미설정)")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
