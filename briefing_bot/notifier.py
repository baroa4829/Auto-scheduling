"""브리핑을 마크다운/텔레그램 형식으로 만들고 텔레그램으로 전송한다."""

from __future__ import annotations

import html
import logging
import os
from datetime import date

import requests

from .scraper import Article

log = logging.getLogger(__name__)

WEEKDAYS = "월화수목금토일"


def _merge(articles: list[Article], summary: dict) -> list[tuple[Article, str]]:
    by_rank = {it["rank"]: it["summary"] for it in summary.get("items", [])}
    return [(a, by_rank.get(a.rank, "")) for a in articles]


def _day_label(day: date) -> str:
    return f"{day:%Y.%m.%d}({WEEKDAYS[day.weekday()]})"


def render_news_markdown(
    title: str,
    day: date,
    collected: dict[str, list[Article]],
    summaries: dict[str, dict],
    new_urls: set[str] | None = None,
    overview: list[str] | None = None,
    notes: list[str] | None = None,
) -> str:
    new_urls = new_urls or set()
    lines = [f"# {title} — {_day_label(day)}", ""]
    for note in notes or []:
        lines.append(f"_※ {note}_")
    if notes:
        lines.append("")
    if overview:
        lines.append("## 🗞️ 오늘 하루 한눈에")
        lines += [f"- {o}" for o in overview]
        lines.append("")
    for section, articles in collected.items():
        if not articles:
            continue
        summary = summaries.get(section, {})
        lines.append(f"## {section}")
        if summary.get("headline"):
            lines.append(f"> {summary['headline']}")
        lines.append("")
        for art, text in _merge(articles, summary):
            press = f" _({art.press})_" if art.press else ""
            new = " 🆕" if art.url in new_urls else ""
            lines.append(f"{art.rank}. **[{art.title}]({art.url})**{press}{new}")
            if text:
                lines.append(f"   - {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_news_telegram(
    title: str,
    day: date,
    collected: dict[str, list[Article]],
    summaries: dict[str, dict],
    new_urls: set[str] | None = None,
    overview: list[str] | None = None,
    notes: list[str] | None = None,
) -> list[str]:
    """텔레그램은 메시지당 4096자 제한이 있어 분야별로 나눠 보낸다 (HTML 모드)."""
    new_urls = new_urls or set()
    head = [f"<b>{html.escape(title)}</b>", _day_label(day)]
    head += [f"<i>※ {html.escape(n)}</i>" for n in notes or []]
    if overview:
        head += ["", "<b>🗞️ 오늘 하루 한눈에</b>"] + [f"• {html.escape(o)}" for o in overview]
    msgs = ["\n".join(head)]
    for section, articles in collected.items():
        if not articles:
            continue
        summary = summaries.get(section, {})
        buf = [f"<b>■ {html.escape(section)}</b>"]
        if summary.get("headline"):
            buf.append(f"<i>{html.escape(summary['headline'])}</i>")
        buf.append("")
        for art, text in _merge(articles, summary):
            new = " 🆕" if art.url in new_urls else ""
            buf.append(
                f'{art.rank}. <a href="{html.escape(art.url)}">{html.escape(art.title)}</a>{new}'
            )
            if text:
                buf.append(f"   └ {html.escape(text)}")
        msgs.append("\n".join(buf)[:4000])
    return msgs


# ---------- 전송 ----------

def send_telegram(token: str, chat_id: str, messages: list[str]) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    for msg in messages:
        resp = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        if not resp.ok:
            ok = False
            log.error("텔레그램 전송 실패: %s %s", resp.status_code, resp.text[:200])
    return ok


def dispatch(markdown: str, telegram_messages: list[str]) -> list[str]:
    """텔레그램으로 전송한다. 설정이 없거나 전송에 실패하면 예외를 던져 실행을 실패 처리한다."""
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 설정되지 않았습니다")
    if not send_telegram(token, chat_id, telegram_messages):
        raise RuntimeError("텔레그램 전송에 실패했습니다 (토큰/채팅 ID 를 확인하세요)")
    return ["telegram"]
