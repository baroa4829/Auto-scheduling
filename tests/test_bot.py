"""네트워크 없이 스크래퍼/렌더링 흐름을 검증하는 테스트."""

import json
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

    # 12시: 오늘 랭킹 정상(어제보다 많음), 1차에 나온 기사(Y1)는 빠진다
    state["thin"] = False
    state["titles"] = ["Y1", "A", "B", "C", "D", "E", "F"]
    calls.clear()
    assert main.main(["news", "--edition", "noon", "--sections", "pol", "--out-dir", str(tmp_path)]) == 0
    md = sent[-1]
    assert "☀️ 2차 뉴스 브리핑" in md
    assert "view/Y1)" not in md and "view/A)" in md and "🆕" not in md

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


def test_dedupe_filters_previous_and_similar(tmp_path):
    from briefing_bot import dedupe

    day_dir = tmp_path / "2026-11-13"
    day_dir.mkdir()
    (day_dir / "1-morning.md").write_text(
        "1. **[[속보] 젠슨 황, 엔비디아 부사장과도 불륜 의혹](https://news.nate.com/view/1)** _(A)_\n"
        "2. **[환율 1450원 돌파](https://news.nate.com/view/2)**\n",
        encoding="utf-8",
    )
    prev = dedupe.previous_articles(day_dir, ["1-morning.md", "2-noon.md"])
    assert len(prev) == 2

    A = scraper.Article
    collected = {
        "세계": [
            A(1, "젠슨 황, 엔비디아 부사장과도 불륜 의혹(종합)", "https://news.nate.com/view/9"),  # 비슷한 제목
            A(2, "환율 1450원 돌파", "https://news.nate.com/view/2"),  # 같은 URL
            A(3, "미 연준 금리 동결 결정", "https://news.nate.com/view/3"),
            A(4, "유럽 증시 일제히 하락", "https://news.nate.com/view/4"),
        ],
        "경제": [
            A(1, "미 연준, 금리 동결 결정", "https://news.nate.com/view/5"),  # 다른 분야와 겹침
            A(2, "반도체 수출 역대 최대", "https://news.nate.com/view/6"),
        ],
    }
    out, dropped = dedupe.filter_new(collected, prev, top_n=1)
    assert [a.rank for a in out["세계"]] == [3]  # 원래 순위 유지, top_n 개만
    assert [a.title for a in out["경제"]] == ["반도체 수출 역대 최대"]
    assert dropped == 3
    assert not dedupe.similar("삼성전자 주가 3% 상승 마감", "삼성전자 주가 5% 하락 마감")
