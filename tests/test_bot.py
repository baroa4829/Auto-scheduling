"""네트워크 없이 스크래퍼/렌더링 흐름을 검증하는 테스트."""

import json
import time
from datetime import date
from types import SimpleNamespace

import requests

from datetime import datetime

from briefing_bot import main, notifier, scraper, summarizer, weather


def _rank_html(n=12):
    top = "".join(
        f'<div class="mlt01"><span class="ico_rank"><em>{i}</em></span>'
        f'<a href="//news.nate.com/view/20261111n{1000+i}?mid=n1006" class="lt1">'
        f'<span class="ib"><img src="x.jpg"></span>'
        f'<span class="tb"><h2 class="tit">기사 제목 번호 {i}</h2></span></a>'
        f'<span class="medium">언론사{i}<em>2026-11-11</em></span></div>'
        for i in range(1, 6)
    )
    rest = "".join(
        f'<li><a href="//news.nate.com/view/20261111n{1000+i}?mid=n1006">기사 제목 번호 {i}</a>'
        f'<span class="medium">언론사{i}<em>2026-11-11</em></span></li>'
        for i in range(6, n + 1)
    )
    return (
        '<html><head><meta charset="euc-kr"></head><body>'
        f'<div class="postRankSubjectList">{top}<ul class="mduSubject">{rest}</ul></div>'
        "</body></html>"
    ).encode("cp949")


def _view_html():
    return (
        '<html><head><meta charset="euc-kr">'
        '<meta property="og:description" content="요약 메타"></head><body>'
        '<div id="realArtcContents"><script>x()</script>' + "본문 내용입니다. " * 30 + "</div>"
        "</body></html>"
    ).encode("cp949")


class FakeResp:
    def __init__(self, content):
        self.content, self.encoding = content, None

    def raise_for_status(self):
        pass


def test_ranking_split_blocks(monkeypatch):
    """1~5위와 6~10위가 다른 블록에 있어도 10개를 모은다."""
    html_ = _rank_html().decode("cp949").replace(
        '<ul class="mduSubject">', '</div><div class="otherBlock"><ul class="mduSubject">'
    ).replace("</ul></div>", "</ul></div>").encode("cp949")
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: FakeResp(html_))
    arts = scraper.fetch_ranking(requests.Session(), "pol", date(2026, 11, 11), 10)
    assert [a.title for a in arts][-1] == "기사 제목 번호 10" and len(arts) == 10


def test_missing_secrets(monkeypatch, caplog, tmp_path):
    for k in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    assert main.main(["news", "--out-dir", str(tmp_path)]) == 1
    assert "ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID" in caplog.text


def test_scrape_rank_and_body(monkeypatch):
    def fake_get(self, url, **kw):
        return FakeResp(_rank_html() if "/rank/" in url else _view_html())

    monkeypatch.setattr(requests.Session, "get", fake_get)
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)

    got = scraper.collect({"pol": "정치"}, date(2026, 11, 11), top_n=10)
    arts = got["정치"]
    assert [a.rank for a in arts] == list(range(1, 11))
    assert arts[0].title == "기사 제목 번호 1"
    assert arts[0].url == "https://news.nate.com/view/20261111n1001"
    assert arts[0].press == "언론사1"
    assert arts[9].title == "기사 제목 번호 10"
    assert arts[0].body.startswith("본문 내용입니다.")
    assert "x()" not in arts[0].body


def test_summarize_and_render(monkeypatch):
    arts = [scraper.Article(rank=i, title=f"제목{i}", url=f"https://n/{i}", press="P") for i in (1, 2)]
    payload = {"headline": "오늘의 흐름", "items": [{"rank": 1, "summary": "요약1"}, {"rank": 2, "summary": "요약2"}]}

    captured = {}

    def fake_create(**kw):
        captured.update(kw)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=json.dumps(payload))],
        )

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=fake_create)))
    out = summarizer.summarize_section(client, "정치", arts)
    assert out == payload
    assert captured["model"] == "claude-opus-5-5"
    assert "제목1" in captured["messages"][0]["content"]

    md = notifier.render_news_markdown("T", date(2026, 11, 11), {"정치": arts}, {"정치": out}, {"https://n/2"})
    assert "## 정치" in md and "> 오늘의 흐름" in md and "   - 요약2" in md
    assert "https://n/2)** _(P)_ 🆕" in md and "https://n/1)** _(P)_\n" in md
    tg = notifier.render_news_telegram("T", date(2026, 11, 11), {"정치": arts}, {"정치": out})
    assert len(tg) == 2 and "<b>■ 정치</b>" in tg[1]


# ---------------- 날씨 ----------------

FAKE_WEATHER = {
    "forecast": {
        "current": {"temperature_2m": 3.4, "apparent_temperature": 0.2, "relative_humidity_2m": 60,
                    "weather_code": 1, "wind_speed_10m": 2.5},
        "daily": {"weather_code": [61], "temperature_2m_max": [12.0], "temperature_2m_min": [1.0],
                  "precipitation_probability_max": [70], "precipitation_sum": [3.2], "uv_index_max": [3]},
        "hourly": {
            "time": [f"2026-11-12T{h:02d}:00" for h in range(24)],
            "temperature_2m": [float(h // 2) for h in range(24)],
            "precipitation_probability": [10] * 12 + [70] * 12,
            "weather_code": [1] * 12 + [61] * 12,
        },
    },
    "air": {"current": {"pm10": 95, "pm2_5": 20}},
}


def test_weather_analyze_and_render():
    r = weather.analyze(weather.Location("서울", 37.5, 127.0), FAKE_WEATHER)
    assert (r["tmin"], r["tmax"], r["rain_prob"]) == (1, 12, 70)
    assert r["pm10_grade"] == "나쁨" and r["pm25_grade"] == "보통"
    assert set(r["slots"]) == {"아침", "낮", "저녁", "밤"}
    assert r["slots"]["저녁"]["rain"] == 70
    tips = " ".join(r["tips"])
    assert "우산" in tips and "일교차" in tips and "마스크" in tips

    md = weather.render_markdown(date(2026, 11, 12), [r])
    assert "## 서울 🌧️ 약한 비" in md and "최저 1°C / 최고 12°C" in md
    tg = weather.render_telegram(date(2026, 11, 12), [r])
    assert len(tg) == 1 and "오늘의 날씨 · 서울" in tg[0]


def test_weather_evening_edition():
    import copy
    data = copy.deepcopy(FAKE_WEATHER)
    d = data["forecast"]["daily"]
    d["weather_code"].append(3)
    d["temperature_2m_max"].append(10.0)
    d["temperature_2m_min"].append(-4.0)
    d["precipitation_probability_max"].append(60)
    r = weather.analyze(weather.Location("동탄", 37.1, 127.1), data)
    assert r["tomorrow"] == {"code": 3, "tmax": 10, "tmin": -4, "rain_prob": 60}
    md = weather.render_markdown(date(2026, 11, 13), [r], edition="evening")
    assert "저녁 날씨 & 내일 예보" in md and "내일 ☁️ 흐림 최저 -4°C" in md
    assert "아침 " not in md and "밤 " in md
    assert "내일 비 소식" in md and "5도 더 추워요" in md
    tg = weather.render_telegram(date(2026, 11, 13), [r], edition="evening")
    assert "🌆 <b>저녁 날씨" in tg[0] and "<b>내일</b>" in tg[0]


def test_weather_multi_location_single_message():
    r1 = weather.analyze(weather.Location("동탄9동", 37.1, 127.1), FAKE_WEATHER)
    r2 = weather.analyze(weather.Location("반월동", 37.2, 127.0), FAKE_WEATHER)
    tg = weather.render_telegram(date(2026, 11, 13), [r1, r2])
    assert len(tg) == 1 and "동탄9동" in tg[0] and "반월동" in tg[0]
    assert [l.name for l in weather.parse_locations(weather.DEFAULT_LOCATIONS)] == ["화성 동탄9동", "화성 반월동"]


def test_parse_locations():
    locs = weather.parse_locations("서울:37.5:127.0, 부산:35.1:129.0")
    assert [l.name for l in locs] == ["서울", "부산"]


# ---------------- 일정/에디션 ----------------

def test_pick_task():
    kst = main.KST
    assert main.pick_task(datetime(2026, 11, 12, 7, 25, tzinfo=kst)) == ("weather", "morning")
    assert main.pick_task(datetime(2026, 11, 12, 17, 5, tzinfo=kst)) == ("weather", "evening")
    assert main.pick_task(datetime(2026, 11, 12, 8, 10, tzinfo=kst)) == ("news", "morning")
    assert main.pick_task(datetime(2026, 11, 12, 11, 50, tzinfo=kst)) == ("news", "noon")
    assert main.pick_task(datetime(2026, 11, 12, 16, 5, tzinfo=kst)) == ("news", "afternoon")
    assert main.pick_task(datetime(2026, 11, 12, 21, 50, tzinfo=kst)) == ("news", "evening")


def test_news_editions_mark_new_and_fallback(monkeypatch, tmp_path):
    today = date(2026, 11, 12)
    monkeypatch.setattr(main, "now_kst", lambda: datetime(2026, 11, 12, 8, 0, tzinfo=main.KST))
    for k in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.setenv(k, "x")

    calls = []
    state = {"titles": ["A", "B", "C", "D", "E", "F"]}

    def fake_collect(session, sections, day, top_n=10):
        calls.append(day)
        arts = state["titles"] if day == today else ["Y1", "Y2", "Y3", "Y4", "Y5", "Y6"]
        if day == today and state.get("thin"):
            arts = arts[:2]
        return {n: [scraper.Article(i + 1, t, f"https://news.nate.com/view/{t}") for i, t in enumerate(arts)]
                for n in sections.values()}

    monkeypatch.setattr(scraper, "collect_rankings", fake_collect)
    monkeypatch.setattr(scraper, "fetch_bodies", lambda session, c: None)
    monkeypatch.setattr(summarizer, "summarize_all", lambda c, tone="": {})
    overview_called = []
    monkeypatch.setattr(summarizer, "summarize_overview", lambda c, s: overview_called.append(1) or ["하루 정리"])
    sent = []
    monkeypatch.setattr(notifier, "dispatch", lambda md, tg: sent.append(md) or ["x"])

    # 08시: 오늘 랭킹이 부족 → 어제 랭킹으로 대체
    state["thin"] = True
    assert main.main(["news", "--edition", "morning", "--sections", "pol", "--out-dir", str(tmp_path)]) == 0
    assert calls == [today, date(2026, 11, 11)]
    assert "어제(11/11) 랭킹을 사용" in sent[-1] and "🆕" not in sent[-1]

    # 12시: 오늘 랭킹 정상(어제보다 많음), 1차와 다른 기사는 모두 🆕
    state["thin"] = False
    state["titles"] = ["Y1", "A", "B", "C", "D", "E", "F"]
    calls.clear()
    assert main.main(["news", "--edition", "noon", "--sections", "pol", "--out-dir", str(tmp_path)]) == 0
    md = sent[-1]
    assert "☀️ 2차 뉴스 브리핑" in md
    assert "view/Y1)** 🆕" not in md and "view/A)** 🆕" in md

    # 22시: 하루 정리 포함
    assert main.main(["news", "--edition", "evening", "--sections", "pol", "--out-dir", str(tmp_path)]) == 0
    assert overview_called and "오늘 하루 한눈에" in sent[-1]
    assert sorted(p.name for p in (tmp_path / "2026-11-12").iterdir()) == ["1-morning.md", "2-noon.md", "4-evening.md"]


def test_telegram_check(monkeypatch, caplog):
    caplog.set_level("INFO")
    class R:
        def __init__(self, data):
            self._d, self.ok, self.status_code, self.text = data, True, 200, ""

        def json(self):
            return self._d

    updates = {"ok": True, "result": [{"message": {"chat": {"id": 555, "first_name": "재훈"}}}]}

    def fake_get(url, **kw):
        if url.endswith("/getMe"):
            return R({"ok": True, "result": {"first_name": "News", "username": "news_bot"}})
        return R(updates)

    posted = []
    monkeypatch.setattr(notifier.requests, "get", fake_get)
    monkeypatch.setattr(notifier.requests, "post", lambda url, **kw: posted.append(kw) or R({}))

    assert notifier.telegram_check("t", "999") == 1
    assert "올바른 채팅 ID: 555" in caplog.text and "@news_bot" in caplog.text
    assert notifier.telegram_check("t", "555") == 0
    assert posted and posted[0]["json"]["chat_id"] == "555"


def test_fetch_bodies_stops_after_consecutive_failures(monkeypatch):
    monkeypatch.setattr(scraper.time, "sleep", lambda *_: None)
    calls = []

    def fake_body(session, art):
        calls.append(art.rank)  # 본문을 못 채움 = 실패

    monkeypatch.setattr(scraper, "fetch_body", fake_body)
    arts = {"정치": [scraper.Article(i, f"t{i}", f"u{i}") for i in range(1, 11)]}
    scraper.fetch_bodies(None, arts)
    assert calls == [1, 2, 3]


def test_skip_already_sent(monkeypatch, tmp_path):
    """예약 실행이 늦게 와서 수동 실행과 겹쳐도 같은 브리핑은 한 번만 보낸다."""
    monkeypatch.setattr(main, "now_kst", lambda: datetime(2026, 11, 13, 7, 30, tzinfo=main.KST))
    for k in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setattr(weather, "build", lambda day, edition="morning": ("# md\n", ["tg"]))
    sent = []
    monkeypatch.setattr(notifier, "dispatch", lambda md, tg: sent.append(md) or ["telegram"])
    args = ["weather", "--out-dir", str(tmp_path)]
    assert main.main(args) == 0
    assert main.main(args) == 0  # 두 번째는 건너뜀
    assert len(sent) == 1
    assert main.main(args + ["--force"]) == 0
    assert len(sent) == 2
    assert (tmp_path / "2026-11-13" / "weather-morning.md").exists()


# ---------------- 증시 리포트 ----------------

from briefing_bot import stocks


def _chart(closes, *, last_day=date(2026, 11, 12), gmtoffset=32400, currency="KRW", volumes=None):
    """last_day 까지 영업일(월~금) 일봉을 흉내 낸 Yahoo 차트 응답."""
    days, d = [], last_day
    while len(days) < len(closes):
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    ts = [int(datetime(x.year, x.month, x.day, tzinfo=timezone.utc).timestamp()) - gmtoffset + 9 * 3600
          for x in days]
    return {
        "meta": {"currency": currency, "gmtoffset": gmtoffset},
        "timestamp": ts,
        "indicators": {"quote": [{"close": closes, "volume": volumes or [1000] * len(closes)}]},
    }


from datetime import timedelta, timezone  # noqa: E402


def test_stock_analyze_signals():
    closes = [100 + i * 0.1 for i in range(200)] + [130]  # 마지막 날 급등 + 신고가
    vols = [1000] * 200 + [3000]
    q = stocks.analyze(stocks.Item("삼성전자", "005930.KS"), _chart(closes, volumes=vols))
    assert q.last_date == date(2026, 11, 12)
    assert round(q.change_pct, 1) == round((130 / 119.9 - 1) * 100, 1)
    assert "🚀 52주 신고가" in q.signals and "📢 거래량 3.0배" in q.signals
    assert any("급등" in s for s in q.signals)
    assert q.rsi14 is not None and q.rsi14 > 70
    assert stocks.fmt_price(q) == "130원" and stocks.fmt_change(q).startswith("🔺")


def test_stock_fmt_rate_and_fx():
    rate = stocks.analyze(stocks.Item("미 10년물", "^TNX", "rate"), _chart([4.20, 4.25], currency="USD"))
    assert stocks.fmt_price(rate) == "4.25%" and stocks.fmt_change(rate) == "🔺5bp"
    jpy = stocks.analyze(stocks.Item("원/엔", "JPYKRW=X", "fx", 100), _chart([9.0, 9.1]))
    assert stocks.fmt_price(jpy) == "910.00원"


def test_parse_watchlist():
    items = stocks.parse_watchlist("삼성전자:005930.KS, 엔비디아:NVDA,AAPL")
    assert [(i.name, i.symbol) for i in items] == [("삼성전자", "005930.KS"), ("엔비디아", "NVDA"), ("AAPL", "AAPL")]


def test_analyze_intraday_uses_market_price_and_last_completed_close():
    """장중: 일봉에 오늘 봉이 있든(종가 null) 없든, 전일 대비는 '확정된 어제 종가' 기준."""
    base = _chart([100.0 + i for i in range(30)])  # 마지막 확정 종가 129 (11/12)
    today_ts = base["timestamp"][-1] + 86400
    # (a) 오늘 봉이 종가 null 로 들어 있는 경우 → 필터링되어 어제 종가 기준
    c = {**base, "timestamp": base["timestamp"] + [today_ts],
         "indicators": {"quote": [{"close": base["indicators"]["quote"][0]["close"] + [None],
                                   "volume": [1000] * 31}]},
         "meta": {**base["meta"], "regularMarketPrice": 135.0, "regularMarketTime": today_ts}}
    q = stocks.analyze(stocks.Item("코스피", "^KS11", "index"), c, intraday=True)
    assert q.price == 135.0 and round(q.change, 1) == 6.0 and q.last_date == date(2026, 11, 13)
    assert q.asof is not None and q.vol_ratio is None
    # (b) 오늘 봉이 일봉에 부분 값으로 들어 있는 경우 → 어제 종가 기준은 동일
    d = {**base, "timestamp": base["timestamp"] + [today_ts],
         "indicators": {"quote": [{"close": base["indicators"]["quote"][0]["close"] + [134.0],
                                   "volume": [1000] * 31}]},
         "meta": {**base["meta"], "regularMarketPrice": 135.0, "regularMarketTime": today_ts}}
    q2 = stocks.analyze(stocks.Item("코스피", "^KS11", "index"), d, intraday=True)
    assert q2.price == 135.0 and round(q2.change, 1) == 6.0


def test_stock_wait_and_gate_windows():
    kst = main.KST
    # 09:03 목표 — 08:50 에 깨어나면 13분 대기
    assert stocks.wait_seconds("kr_open", datetime(2026, 11, 16, 8, 50, tzinfo=kst)) == 13 * 60
    assert stocks.wait_seconds("kr_open", datetime(2026, 11, 16, 9, 10, tzinfo=kst)) == 0  # 늦으면 바로 실행
    assert stocks.wait_seconds("kr_open", datetime(2026, 11, 16, 8, 20, tzinfo=kst)) is None  # 너무 이름
    assert stocks.wait_seconds("kr_open", datetime(2026, 11, 16, 10, 0, tzinfo=kst)) is None  # 너무 늦음


def test_us_open_follows_daylight_saving():
    utc = timezone.utc
    # 겨울(EST): 목표 23:33 KST = 14:33 UTC → 14:20 cron 만 실행, 13:20 cron 은 건너뜀
    assert stocks.wait_seconds("us_open", datetime(2026, 11, 16, 14, 20, tzinfo=utc)) == 13 * 60
    assert stocks.wait_seconds("us_open", datetime(2026, 11, 16, 13, 20, tzinfo=utc)) is None
    # 여름(EDT): 목표 22:33 KST = 13:33 UTC → 13:20 cron 만 실행, 14:20 cron 은 건너뜀
    assert stocks.wait_seconds("us_open", datetime(2026, 7, 15, 13, 20, tzinfo=utc)) == 13 * 60
    assert stocks.wait_seconds("us_open", datetime(2026, 7, 15, 14, 20, tzinfo=utc)) is None
    assert stocks.target_time("us_open", datetime(2026, 11, 16, 14, 20, tzinfo=utc)).astimezone(main.KST).strftime("%H:%M") == "23:33"
    assert stocks.target_time("us_open", datetime(2026, 7, 15, 13, 20, tzinfo=utc)).astimezone(main.KST).strftime("%H:%M") == "22:33"


def test_expected_session_dates():
    kst = main.KST
    assert stocks.expected_session("kr_open", datetime(2026, 11, 16, 9, 3, tzinfo=kst)) == date(2026, 11, 16)
    # 화요일 07:00 KST = 월요일 17:00 ET → 미국 세션 날짜는 월요일
    assert stocks.expected_session("us_close", datetime(2026, 11, 17, 7, 0, tzinfo=kst)) == date(2026, 11, 16)
    # 월요일 23:33 KST = 월요일 09:33 ET
    assert stocks.expected_session("us_open", datetime(2026, 11, 16, 23, 33, tzinfo=kst)) == date(2026, 11, 16)


def test_watchlist_split_by_market():
    items = stocks.parse_watchlist()
    kr = stocks.watchlist_for("kr_noon", items)
    us = stocks.watchlist_for("us_open", items)
    assert len(kr) == 7 and all(i.symbol.endswith((".KS", ".KQ")) for i in kr)
    assert len(us) == 15 and not any(i.is_kr for i in us) and len(kr) + len(us) == len(items)


def _stock_env(monkeypatch, now, sleeps):
    monkeypatch.setattr(main, "now_kst", lambda: now)
    # main.time 과 stocks.time 은 같은 모듈이다. 시세 조회 간격(1초 미만)은 무시하고 긴 대기만 기록한다.
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s) if s >= 30 else None)

    def fake_get(self, url, **kw):
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"chart": {"result": [_chart([100.0 + i for i in range(30)])]}})

    monkeypatch.setattr(requests.Session, "get", fake_get)
    monkeypatch.setattr(stocks, "economy_headlines", lambda day: ["반도체 수출 증가"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    sent = []
    monkeypatch.setattr(notifier, "dispatch", lambda md, tg: sent.append((md, tg)) or ["telegram"])
    return sent


def test_run_stock_end_to_end(monkeypatch, tmp_path):
    sleeps = []
    sent = _stock_env(monkeypatch, datetime(2026, 11, 12, 15, 20, tzinfo=main.KST), sleeps)
    seen = {}
    monkeypatch.setattr(stocks, "market_comment",
                        lambda ed, q, h: seen.setdefault("h", h) and {"headline": "코스피 상승", "points": ["반도체 강세"], "watch": ["환율"]})

    rc = main.main(["stock", "--edition", "kr_close", "--out-dir", str(tmp_path), "--watchlist", "삼성전자:005930.KS,엔비디아:NVDA"])
    assert rc == 0 and seen["h"] == ["반도체 수출 증가"] and sleeps == []
    md, tg = sent[0]
    assert "⏰ 국장 마감 10분 전" in md and "| 삼성전자 |" in md and "코스피 상승" in md
    assert "엔비디아" not in md  # 국장 에디션엔 미국 종목 제외
    assert len(tg) == 1 and "<b>■ ⭐ 관심 종목(국내)</b>" in tg[0] and "투자 권유가 아닙니다" in tg[0]
    assert (tmp_path / "2026-11-12" / "stock-kr_close.md").exists()

    # 같은 날 다시 실행하면 건너뜀
    assert main.main(["stock", "--edition", "kr_close", "--out-dir", str(tmp_path)]) == 0 and len(sent) == 1


def test_run_stock_waits_until_target_then_sends(monkeypatch, tmp_path):
    sleeps = []
    sent = _stock_env(monkeypatch, datetime(2026, 11, 12, 11, 48, tzinfo=main.KST), sleeps)
    monkeypatch.setattr(stocks, "market_comment", lambda ed, q, h: None)
    assert main.main(["stock", "--edition", "kr_noon", "--out-dir", str(tmp_path), "--watchlist", "삼성전자:005930.KS"]) == 0
    assert sleeps == [12 * 60] and len(sent) == 1


def test_run_stock_skips_wrong_time_and_holiday(monkeypatch, tmp_path):
    sleeps = []
    sent = _stock_env(monkeypatch, datetime(2026, 11, 12, 13, 0, tzinfo=main.KST), sleeps)
    # 목표(15:20)보다 너무 이른 실행 → 건너뜀 (대기 없음)
    assert main.main(["stock", "--edition", "kr_close", "--out-dir", str(tmp_path)]) == 0
    assert sent == [] and sleeps == []
    # 휴장일: 코스피 최신 시세가 어제까지 → 재시도 후에도 오늘이 아니면 건너뜀
    monkeypatch.setattr(main, "now_kst", lambda: datetime(2026, 11, 13, 15, 20, tzinfo=main.KST))
    assert main.main(["stock", "--edition", "kr_close", "--out-dir", str(tmp_path)]) == 0
    assert sent == [] and sleeps == [45, 45]
    assert not (tmp_path / "2026-11-13" / "stock-kr_close.md").exists()
    # 수동 실행(--force)은 대기·휴장 확인 없이 보낸다
    monkeypatch.setattr(stocks, "market_comment", lambda ed, q, h: None)
    assert main.main(["stock", "--edition", "kr_close", "--force", "--out-dir", str(tmp_path), "--watchlist", "삼성전자:005930.KS"]) == 0
    assert len(sent) == 1


def test_pick_task_stock():
    kst = main.KST
    assert main.pick_task(datetime(2026, 11, 12, 9, 0, tzinfo=kst)) == ("stock", "kr_open")
    assert main.pick_task(datetime(2026, 11, 12, 15, 25, tzinfo=kst)) == ("stock", "kr_close")
    assert main.pick_task(datetime(2026, 11, 12, 23, 30, tzinfo=kst)) == ("stock", "us_open")
    assert main.pick_task(datetime(2026, 11, 12, 6, 55, tzinfo=kst)) == ("stock", "us_close")


def test_default_watchlist_and_long_telegram_split():
    items = stocks.parse_watchlist()
    assert len(items) == 22 and all(i.symbol and i.name for i in items)
    assert ("TIGER 미국S&P500", "360750.KS") in [(i.name, i.symbol) for i in items]
    qs = [stocks.analyze(i, _chart([100.0 + k for k in range(30)])) for i in items]
    msgs = stocks.render_telegram("kr_close", date(2026, 11, 12), {"⭐ 관심 종목": qs * 2}, {"headline": "h", "points": ["p"], "watch": ["w"]})
    assert len(msgs) >= 2 and all(len(m) <= 4000 for m in msgs)
    assert sum(m.count("삼성전자") for m in msgs) == 2  # 잘려 나간 종목 없음


def test_fmt_change_arrows():
    up = stocks.analyze(stocks.Item("a", "A"), _chart([100.0, 101.0]))
    down = stocks.analyze(stocks.Item("b", "B"), _chart([100.0, 99.0]))
    flat = stocks.analyze(stocks.Item("c", "C"), _chart([100.0, 100.0]))
    assert stocks.fmt_change(up) == "🔺1.00%"
    assert stocks.fmt_change(down) == "🔽1.00%"
    assert stocks.fmt_change(flat) == "➖0.00%"
