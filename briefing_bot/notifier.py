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
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not (token and chat_id):
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 설정되지 않았습니다")
    if not send_telegram(token, chat_id, telegram_messages):
        raise RuntimeError("텔레그램 전송에 실패했습니다 (토큰/채팅 ID 를 확인하세요)")
    return ["telegram"]


# ---------- 텔레그램 설정 진단 ----------

def telegram_check(token: str, chat_id: str) -> int:
    """토큰이 어떤 봇인지, 그 봇에게 메시지를 보낸 채팅 ID 가 무엇인지 확인한다.

    값 자체는 로그에 남기지 않고, 설정된 채팅 ID 와 일치하는지만 알려준다.
    """
    base = f"https://api.telegram.org/bot{token}"
    me = requests.get(f"{base}/getMe", timeout=15).json()
    if not me.get("ok"):
        log.error("❌ 봇 토큰이 올바르지 않습니다: %s", me.get("description"))
        return 1
    bot = me["result"]
    log.info("✅ 토큰 정상 — 이 토큰의 봇: %s (@%s)", bot.get("first_name"), bot.get("username"))

    upd = requests.get(f"{base}/getUpdates", timeout=15).json()
    if not upd.get("ok"):
        log.error("getUpdates 실패: %s", upd.get("description"))
        return 1

    chats: dict[str, str] = {}
    for u in upd.get("result", []):
        msg = u.get("message") or u.get("edited_message") or u.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if "id" in chat:
            chats[str(chat["id"])] = chat.get("first_name") or chat.get("title") or ""

    configured = (chat_id or "").strip()
    if not chats:
        log.error(
            "❌ @%s 봇이 최근 받은 메시지가 없습니다. 텔레그램에서 @%s 를 열고 "
            "'안녕' 같은 메시지를 보낸 뒤 다시 실행하세요.",
            bot.get("username"), bot.get("username"),
        )
        return 1

    log.info("@%s 에게 메시지를 보낸 사람: %s", bot.get("username"),
             ", ".join(f"{name or '이름없음'}" for name in chats.values()))
    if configured in chats:
        log.info("✅ TELEGRAM_CHAT_ID 가 %s 님의 채팅 ID 와 일치합니다.", chats[configured])
        ok = send_telegram(token, configured, ["✅ 텔레그램 연결 테스트 성공! 브리핑이 이 채팅으로 옵니다."])
        return 0 if ok else 1

    for cid, name in chats.items():
        # 채팅 ID 는 비밀값이 아니므로 그대로 보여줘 Secret 에 넣을 수 있게 한다
        log.error("❌ TELEGRAM_CHAT_ID 가 일치하지 않습니다. %s 님의 올바른 채팅 ID: %s", name or "이름없음", cid)
    if configured != chat_id:
        log.error("(참고: 설정된 값 앞뒤에 공백이 있습니다)")
    return 1
