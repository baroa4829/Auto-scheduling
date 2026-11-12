"""주식 시장 동향 리포트: Yahoo Finance 차트 API(키 불필요)로 시세를 모아 정리한다.

에디션
    morning  08:30 KST  간밤 미국 증시 마감 + 환율·원자재·금리 + 관심 종목 → 오늘 국내장 체크포인트
    close    16:10 KST  국내 증시 마감 + 아시아 증시 + 환율 + 관심 종목 → 오늘 장 정리
"""

from __future__ import annotations

import html
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import requests

log = logging.getLogger(__name__)

CHART_URLS = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
    "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
}
WEEKDAYS = "월화수목금토일"

# 관심 종목 기본값. GitHub 저장소 Variables 의 STOCK_WATCHLIST 로 바꿀 수 있다.
# 형식: "이름:야후심볼,..."  (국내 코스피 종목은 6자리코드.KS, 코스닥은 .KQ)
DEFAULT_WATCHLIST = (
    "삼성전자:005930.KS,SK하이닉스:000660.KS,현대차:005380.KS,"
    "엔비디아:NVDA,애플:AAPL,테슬라:TSLA"
)


@dataclass(frozen=True)
class Item:
    name: str
    symbol: str
    kind: str = "stock"  # index | fx | commodity | rate | crypto | stock
    scale: float = 1.0  # 표시 단위 보정 (예: 원/엔을 100엔 기준으로)


# 에디션별 시장 지표 묶음 (그룹 제목 → 항목)
MARKETS: dict[str, dict[str, list[Item]]] = {
    "morning": {
        "🇺🇸 미국 증시": [
            Item("S&P500", "^GSPC", "index"),
            Item("나스닥", "^IXIC", "index"),
            Item("다우", "^DJI", "index"),
            Item("필라델피아 반도체", "^SOX", "index"),
            Item("VIX(공포지수)", "^VIX", "index"),
        ],
        "💱 환율·원자재·금리": [
            Item("원/달러", "KRW=X", "fx"),
            Item("달러인덱스", "DX-Y.NYB", "index"),
            Item("WTI 유가", "CL=F", "commodity"),
            Item("금", "GC=F", "commodity"),
            Item("미 10년물 금리", "^TNX", "rate"),
            Item("비트코인", "BTC-USD", "crypto"),
        ],
    },
    "close": {
        "🇰🇷 국내 증시": [
            Item("코스피", "^KS11", "index"),
            Item("코스닥", "^KQ11", "index"),
        ],
        "🌏 아시아 증시": [
            Item("닛케이225", "^N225", "index"),
            Item("상해종합", "000001.SS", "index"),
            Item("항셍", "^HSI", "index"),
        ],
        "💱 환율": [
            Item("원/달러", "KRW=X", "fx"),
            Item("원/엔(100엔)", "JPYKRW=X", "fx", 100),
        ],
    },
}

TITLES = {"morning": "🌅 아침 증시 브리핑", "close": "📊 장 마감 증시 리포트"}

# 휴장일 판별 기준: 이 지표의 마지막 거래일이 기대한 날짜가 아니면 휴장으로 본다
ANCHOR = {"morning": "^GSPC", "close": "^KS11"}


@dataclass
class Quote:
    item: Item
    currency: str = ""
    last_date: date | None = None  # 거래소 현지 기준 마지막 거래일
    price: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0
    chg_5d: float | None = None
    chg_20d: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    ma20: float | None = None
    ma60: float | None = None
    rsi14: float | None = None
    vol_ratio: float | None = None  # 오늘 거래량 / 20일 평균
    signals: list[str] = field(default_factory=list)


def parse_watchlist(spec: str | None = None) -> list[Item]:
    spec = spec or os.environ.get("STOCK_WATCHLIST") or DEFAULT_WATCHLIST
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, symbol = part.rpartition(":")
        out.append(Item((name or symbol).strip(), symbol.strip(), "stock"))
    return out


# ---------------- 수집 ----------------

def fetch_chart(session: requests.Session, symbol: str) -> dict:
    """1년치 일봉. query1 이 막히면 query2 로 재시도."""
    last_exc: Exception | None = None
    for attempt, base in enumerate(CHART_URLS * 2):
        try:
            resp = session.get(
                base.format(symbol=requests.utils.quote(symbol, safe="")),
                params={"range": "1y", "interval": "1d", "includePrePost": "false"},
                headers=HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            result = (resp.json().get("chart") or {}).get("result")
            if not result:
                raise ValueError(f"빈 응답: {symbol}")
            return result[0]
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"시세 조회 실패: {symbol}") from last_exc


def _pct(a: float, b: float) -> float:
    return (a / b - 1) * 100 if b else 0.0


def _rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) <= n:
        return None
    diffs = [b - a for a, b in zip(closes[:-1], closes[1:])]
    gains = [max(d, 0) for d in diffs]
    losses = [max(-d, 0) for d in diffs]
    # Wilder 평활
    avg_g, avg_l = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n
    if avg_l == 0:
        return 100.0
    return 100 - 100 / (1 + avg_g / avg_l)


def analyze(item: Item, chart: dict) -> Quote:
    meta = chart.get("meta", {})
    q = (chart.get("indicators", {}).get("quote") or [{}])[0]
    offset = timedelta(seconds=meta.get("gmtoffset", 0))
    rows = [
        (datetime.fromtimestamp(ts, timezone.utc) + offset, c, v)
        for ts, c, v in zip(chart.get("timestamp") or [], q.get("close") or [], q.get("volume") or [])
        if c is not None
    ]
    if len(rows) < 2:
        raise ValueError(f"데이터 부족: {item.symbol}")
    closes = [c * item.scale for _, c, _ in rows]
    vols = [v or 0 for _, _, v in rows]
    price, prev = closes[-1], closes[-2]

    quote = Quote(
        item=item,
        currency=meta.get("currency", ""),
        last_date=rows[-1][0].date(),
        price=price,
        change=price - prev,
        change_pct=_pct(price, prev),
        chg_5d=_pct(price, closes[-6]) if len(closes) > 5 else None,
        chg_20d=_pct(price, closes[-21]) if len(closes) > 20 else None,
        high_52w=max(closes),
        low_52w=min(closes),
        ma20=sum(closes[-20:]) / 20 if len(closes) >= 20 else None,
        ma60=sum(closes[-60:]) / 60 if len(closes) >= 60 else None,
        rsi14=_rsi(closes),
    )
    past = [v for v in vols[-21:-1] if v]
    if vols[-1] and len(past) >= 10:
        quote.vol_ratio = vols[-1] / (sum(past) / len(past))

    s = quote.signals
    if len(closes) >= 120 and price >= quote.high_52w:
        s.append("🚀 52주 신고가")
    elif len(closes) >= 120 and price <= quote.low_52w:
        s.append("🧊 52주 신저가")
    if quote.ma20 and len(closes) >= 21:
        prev_ma20 = sum(closes[-21:-1]) / 20
        if prev <= prev_ma20 and price > quote.ma20:
            s.append("↗️ 20일선 돌파")
        elif prev >= prev_ma20 and price < quote.ma20:
            s.append("↘️ 20일선 이탈")
    if quote.rsi14 is not None and item.kind in ("stock", "index"):
        if quote.rsi14 >= 70:
            s.append("🔥 과열(RSI 70↑)")
        elif quote.rsi14 <= 30:
            s.append("🥶 과매도(RSI 30↓)")
    if quote.vol_ratio and quote.vol_ratio >= 2 and item.kind == "stock":
        s.append(f"📢 거래량 {quote.vol_ratio:.1f}배")
    if abs(quote.change_pct) >= 5 and item.kind in ("stock", "crypto"):
        s.append("⚡ 급등" if quote.change_pct > 0 else "⚡ 급락")
    return quote


def collect(edition: str, watchlist: list[Item]) -> dict[str, list[Quote]]:
    groups = {**MARKETS[edition], "⭐ 관심 종목": watchlist}
    out: dict[str, list[Quote]] = {}
    session = requests.Session()
    try:
        for title, items in groups.items():
            out[title] = []
            for it in items:
                try:
                    out[title].append(analyze(it, fetch_chart(session, it.symbol)))
                except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                    log.error("시세 조회 실패 (%s %s): %s", it.name, it.symbol, exc)
                time.sleep(0.3)
    finally:
        session.close()
    return out


def is_market_day(edition: str, day: date, quotes: dict[str, list[Quote]]) -> bool:
    """morning: 미국장이 어제(현지) 열렸는지, close: 국내장이 오늘 열렸는지."""
    expected = day - timedelta(days=1) if edition == "morning" else day
    for qs in quotes.values():
        for q in qs:
            if q.item.symbol == ANCHOR[edition]:
                return q.last_date == expected
    return True  # 기준 지표를 못 가져오면 판단 보류 (그냥 보낸다)


# ---------------- 표시 ----------------

def fmt_price(q: Quote) -> str:
    p, k = q.price, q.item.kind
    if k == "rate":
        return f"{p:.2f}%"
    if q.currency == "KRW" and k == "stock":
        return f"{p:,.0f}원"
    if k == "fx":
        return f"{p:,.2f}원" if q.item.symbol.endswith("KRW=X") else f"{p:,.4f}"
    if q.currency == "USD" and k in ("stock", "crypto", "commodity"):
        return f"${p:,.2f}" if p < 10000 else f"${p:,.0f}"
    if q.currency == "JPY" and k == "stock":
        return f"¥{p:,.0f}"
    return f"{p:,.2f}"


def fmt_change(q: Quote) -> str:
    arrow = "▲" if q.change > 0 else "▼" if q.change < 0 else "—"
    if q.item.kind == "rate":
        return f"{arrow}{abs(q.change) * 100:.0f}bp"
    return f"{arrow}{abs(q.change_pct):.2f}%"


def _extra(q: Quote) -> str:
    bits = []
    if q.chg_5d is not None:
        bits.append(f"5일 {q.chg_5d:+.1f}%")
    if q.chg_20d is not None:
        bits.append(f"20일 {q.chg_20d:+.1f}%")
    if q.rsi14 is not None and q.item.kind in ("stock", "index"):
        bits.append(f"RSI {q.rsi14:.0f}")
    return " · ".join(bits)


def _day_label(day: date) -> str:
    return f"{day:%Y.%m.%d}({WEEKDAYS[day.weekday()]})"


DISCLAIMER = "투자 판단의 참고 자료일 뿐 투자 권유가 아닙니다. 시세는 지연될 수 있습니다."


def render_markdown(edition: str, day: date, quotes: dict[str, list[Quote]],
                    comment: dict | None = None) -> str:
    lines = [f"# {TITLES[edition]} — {_day_label(day)}", ""]
    if comment and comment.get("headline"):
        lines += [f"> **{comment['headline']}**", ""]
    for title, qs in quotes.items():
        if not qs:
            continue
        lines += [f"## {title}", "", "| 종목 | 현재가 | 등락 | 5일 | 20일 | RSI | 신호 |",
                  "|---|---:|---:|---:|---:|---:|---|"]
        for q in qs:
            lines.append(
                f"| {q.item.name} | {fmt_price(q)} | {fmt_change(q)} | "
                f"{'' if q.chg_5d is None else f'{q.chg_5d:+.1f}%'} | "
                f"{'' if q.chg_20d is None else f'{q.chg_20d:+.1f}%'} | "
                f"{'' if q.rsi14 is None else f'{q.rsi14:.0f}'} | {' '.join(q.signals)} |"
            )
        lines.append("")
    if comment:
        if comment.get("points"):
            lines.append("## 🧭 시장 코멘트")
            lines += [f"- {p}" for p in comment["points"]]
            lines.append("")
        if comment.get("watch"):
            lines.append("## 👀 체크포인트")
            lines += [f"- {p}" for p in comment["watch"]]
            lines.append("")
    lines.append(f"_※ {DISCLAIMER}_")
    return "\n".join(lines) + "\n"


def render_telegram(edition: str, day: date, quotes: dict[str, list[Quote]],
                    comment: dict | None = None) -> list[str]:
    e = html.escape
    head = [f"<b>{e(TITLES[edition])}</b>", _day_label(day)]
    if comment and comment.get("headline"):
        head += ["", f"<b>{e(comment['headline'])}</b>"]
    body = []
    for title, qs in quotes.items():
        if not qs:
            continue
        body += ["", f"<b>■ {e(title)}</b>"]
        for q in qs:
            line = f"{e(q.item.name)}  <b>{e(fmt_price(q))}</b>  {fmt_change(q)}"
            if q.item.kind == "stock":
                extra = _extra(q)
                if extra:
                    line += f"\n   <i>{e(extra)}</i>"
            if q.signals:
                line += "\n   " + e(" ".join(q.signals))
            body.append(line)
    tail = []
    if comment:
        if comment.get("points"):
            tail += ["", "<b>🧭 시장 코멘트</b>"] + [f"• {e(p)}" for p in comment["points"]]
        if comment.get("watch"):
            tail += ["", "<b>👀 체크포인트</b>"] + [f"• {e(p)}" for p in comment["watch"]]
    tail += ["", f"<i>※ {e(DISCLAIMER)}</i>"]

    full = "\n".join(head + body + tail)
    if len(full) <= 4000:
        return [full]
    # 길면 시세 / 코멘트로 나눠 보낸다
    return ["\n".join(head + body)[:4000], "\n".join(tail).strip()[:4000]]


# ---------------- Claude 코멘트 ----------------

COMMENT_PROMPT = """\
당신은 한국 개인 투자자를 위한 증시 브리핑 에디터입니다. 시세 데이터와 오늘의 경제 뉴스 제목을 받아
짧은 시장 코멘트를 씁니다.

규칙:
- headline: 오늘 시장을 한 문장(50자 이내)으로 요약합니다.
- points: 3~4개. 지수·업종·환율·금리 등 데이터에서 읽히는 흐름과 관심 종목의 눈에 띄는 움직임을 설명합니다.
  각 항목 한 문장, 90자 이내.
- watch: 2~3개. {watch_hint}
- 숫자는 입력 데이터에 있는 것만 씁니다. 뉴스 제목으로 이유를 설명할 땐 '~영향으로 보인다' 처럼 단정하지 않습니다.
- 입력에 없는 사실을 지어내지 않습니다. 매수/매도 추천이나 목표가는 쓰지 않습니다.
- '~했다/~이다' 체로 간결하게 씁니다.
"""

WATCH_HINT = {
    "morning": "간밤 미국장과 환율을 바탕으로 오늘 국내장에서 지켜볼 점",
    "close": "오늘 마감 흐름을 바탕으로 오늘 밤 미국장이나 내일 국내장에서 지켜볼 점",
}

COMMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "points": {"type": "array", "items": {"type": "string"}},
        "watch": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "points", "watch"],
    "additionalProperties": False,
}


def _comment_input(quotes: dict[str, list[Quote]], headlines: list[str]) -> str:
    parts = []
    for title, qs in quotes.items():
        parts.append(f"[{title}]")
        for q in qs:
            parts.append(
                f"- {q.item.name}({q.item.symbol}) {fmt_price(q)} {fmt_change(q)}"
                f"{' / ' + _extra(q) if _extra(q) else ''}"
                f"{' / ' + ', '.join(q.signals) if q.signals else ''}"
            )
    if headlines:
        parts.append("\n[오늘의 경제 뉴스 많이 본 기사 제목]")
        parts += [f"- {h}" for h in headlines]
    return "\n".join(parts)


def market_comment(edition: str, quotes: dict[str, list[Quote]], headlines: list[str]) -> dict | None:
    import anthropic

    from .summarizer import _ask_json

    system = COMMENT_PROMPT.format(watch_hint=WATCH_HINT[edition])
    try:
        return _ask_json(anthropic.Anthropic(), system, COMMENT_SCHEMA,
                         _comment_input(quotes, headlines), "stock")
    except (anthropic.APIError, RuntimeError, json.JSONDecodeError, KeyError) as exc:
        log.error("시장 코멘트 생성 실패, 시세만 보냅니다: %s", exc)
        return None


def economy_headlines(day: date, top_n: int = 10) -> list[str]:
    """네이트 경제 분야 많이 본 뉴스 제목 (코멘트의 맥락용, 실패해도 무시)."""
    from . import scraper

    session = requests.Session()
    try:
        arts = scraper.fetch_ranking(session, "eco", day, top_n)
        if len(arts) < 3:  # 이른 아침엔 오늘 랭킹이 비어 있을 수 있음
            arts = scraper.fetch_ranking(session, "eco", day - timedelta(days=1), top_n)
        return [a.title for a in arts]
    except Exception as exc:  # noqa: BLE001 - 맥락 정보라 어떤 실패든 무시
        log.warning("경제 뉴스 제목 수집 실패: %s", exc)
        return []
    finally:
        session.close()
