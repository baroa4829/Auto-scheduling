"""브리핑을 마크다운으로 만들고 텔레그램/슬랙/디스코드로 전송한다."""

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


def render_markdown(
    day: date, collected: dict[str, list[Article]], summaries: dict[str, dict]
) -> str:
    lines = [f"# 📰 네이트 뉴스 분야별 Top10 브리핑 — {day:%Y.%m.%d}({WEEKDAYS[day.weekday()]})", ""]
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
            lines.append(f"{art.rank}. **[{art.title}]({art.url})**{press}")
            if text:
                lines.append(f"   - {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------- Telegram ----------

def _telegram_messages(
    day: date, collected: dict[str, list[Article]], summaries: dict[str, dict]
) -> list[str]:
    """텔레그램은 메시지당 4096자 제한이 있어 분야별로 나눠 보낸다 (HTML 모드)."""
    msgs = [f"📰 <b>네이트 뉴스 분야별 Top10 브리핑</b>\n{day:%Y.%m.%d}({WEEKDAYS[day.weekday()]})"]
    for section, articles in collected.items():
        if not articles:
            continue
        summary = summaries.get(section, {})
        buf = [f"<b>■ {html.escape(section)}</b>"]
        if summary.get("headline"):
            buf.append(f"<i>{html.escape(summary['headline'])}</i>")
        buf.append("")
        for art, text in _merge(articles, summary):
            buf.append(f'{art.rank}. <a href="{html.escape(art.url)}">{html.escape(art.title)}</a>')
            if text:
                buf.append(f"   └ {html.escape(text)}")
        msg = "\n".join(buf)
        msgs.append(msg[:4000])
    return msgs


def send_telegram(token: str, chat_id: str, messages: list[str]) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
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
            log.error("텔레그램 전송 실패: %s %s", resp.status_code, resp.text[:200])


# ---------- Slack / Discord (webhook) ----------

def _chunks(text: str, limit: int) -> list[str]:
    out, cur = [], ""
    for block in text.split("\n## "):
        piece = block if not out and not cur else "## " + block
        if len(cur) + len(piece) + 1 > limit and cur:
            out.append(cur)
            cur = ""
        cur += ("\n" if cur else "") + piece
    if cur:
        out.append(cur)
    return [c[:limit] for c in out]


def send_slack(webhook: str, markdown: str) -> None:
    # Slack mrkdwn: **굵게** → *굵게*, [t](u) → <u|t>
    import re

    text = re.sub(r"\*\*\[(.+?)\]\((.+?)\)\*\*", r"*<\2|\1>*", markdown)
    text = re.sub(r"^#+ (.*)$", r"*\1*", text, flags=re.M)
    for chunk in _chunks(text, 3500):
        resp = requests.post(webhook, json={"text": chunk}, timeout=15)
        if not resp.ok:
            log.error("슬랙 전송 실패: %s %s", resp.status_code, resp.text[:200])


def send_discord(webhook: str, markdown: str) -> None:
    for chunk in _chunks(markdown, 1900):
        resp = requests.post(webhook, json={"content": chunk}, timeout=15)
        if not resp.ok:
            log.error("디스코드 전송 실패: %s %s", resp.status_code, resp.text[:200])


def dispatch(
    day: date, collected: dict[str, list[Article]], summaries: dict[str, dict], markdown: str
) -> list[str]:
    """설정된 채널로 전송하고, 전송한 채널 이름 목록을 반환."""
    sent = []
    tg_token, tg_chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if tg_token and tg_chat:
        send_telegram(tg_token, tg_chat, _telegram_messages(day, collected, summaries))
        sent.append("telegram")
    if hook := os.environ.get("SLACK_WEBHOOK_URL"):
        send_slack(hook, markdown)
        sent.append("slack")
    if hook := os.environ.get("DISCORD_WEBHOOK_URL"):
        send_discord(hook, markdown)
        sent.append("discord")
    return sent
