"""브리핑을 마크다운/텔레그램 형식으로 만들고 텔레그램·슬랙·디스코드로 전송한다."""

from __future__ import annotations

import html
import logging
import os
import re
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


def _chunks(text: str, limit: int) -> list[str]:
    """'## ' 섹션 단위로 limit 이하 조각으로 나눈다."""
    out, cur = [], ""
    for i, block in enumerate(text.split("\n## ")):
        piece = block if i == 0 else "## " + block
        if cur and len(cur) + len(piece) + 1 > limit:
            out.append(cur)
            cur = ""
        cur += ("\n" if cur else "") + piece
    if cur:
        out.append(cur)
    return [c[:limit] for c in out]


def to_slack_mrkdwn(markdown: str) -> str:
    text = re.sub(r"\*\*\[(.+?)\]\((.+?)\)\*\*", r"*<\2|\1>*", markdown)
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r"<\2|\1>", text)
    return re.sub(r"^#+ (.*)$", r"*\1*", text, flags=re.M)


def send_webhook(webhook: str, key: str, chunks: list[str], name: str) -> bool:
    ok = True
    for chunk in chunks:
        resp = requests.post(webhook, json={key: chunk}, timeout=15)
        if not resp.ok:
            ok = False
            log.error("%s 전송 실패: %s %s", name, resp.status_code, resp.text[:200])
    return ok


def dispatch(markdown: str, telegram_messages: list[str]) -> list[str]:
    """환경변수로 설정된 채널로 전송하고, 전송한 채널 이름 목록을 반환."""
    sent = []
    tg_token, tg_chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if tg_token and tg_chat and send_telegram(tg_token, tg_chat, telegram_messages):
        sent.append("telegram")
    if hook := os.environ.get("SLACK_WEBHOOK_URL"):
        if send_webhook(hook, "text", _chunks(to_slack_mrkdwn(markdown), 3500), "슬랙"):
            sent.append("slack")
    if hook := os.environ.get("DISCORD_WEBHOOK_URL"):
        if send_webhook(hook, "content", _chunks(markdown, 1900), "디스코드"):
            sent.append("discord")
    return sent
