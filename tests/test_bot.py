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
    assert set(r["slots"]) == {"아침", "낮", "저녁"}
    assert r["slots"]["저녁"]["rain"] == 70
    tips = " ".join(r["tips"])
    assert "우산" in tips and "일교차" in tips and "마스크" in tips

    md = weather.render_markdown(date(2026, 11, 12), [r])
    assert "## 서울 🌧️ 약한 비" in md and "최저 1°C / 최고 12°C" in md
    tg = weather.render_telegram(date(2026, 11, 12), [r])
    assert len(tg) == 1 and "오늘의 날씨 · 서울" in tg[0]


def test_parse_locations():
    locs = weather.parse_locations("서울:37.5:127.0, 부산:35.1:129.0")
    assert [l.name for l in locs] == ["서울", "부산"]


# ---------------- 일정/에디션 ----------------

def test_pick_task():
    kst = main.KST
    assert main.pick_task(datetime(2026, 11, 12, 6, 55, tzinfo=kst)) == ("weather", None)
    assert main.pick_task(datetime(2026, 11, 12, 8, 10, tzinfo=kst)) == ("news", "morning")
    assert main.pick_task(datetime(2026, 11, 12, 11, 50, tzinfo=kst)) == ("news", "noon")
    assert main.pick_task(datetime(2026, 11, 12, 16, 5, tzinfo=kst)) == ("news", "afternoon")
    assert main.pick_task(datetime(2026, 11, 12, 21, 50, tzinfo=kst)) == ("news", "evening")


def test_news_editions_mark_new_and_fallback(monkeypatch, tmp_path):
    today = date(2026, 11, 12)
    monkeypatch.setattr(main, "now_kst", lambda: datetime(2026, 11, 12, 8, 0, tzinfo=main.KST))

    calls = []
    state = {"titles": ["A", "B", "C", "D", "E", "F"]}

    def fake_collect(sections, day, top_n=10, delay=0.3):
        calls.append(day)
        arts = state["titles"] if day == today else ["Y1", "Y2", "Y3", "Y4", "Y5", "Y6"]
        if day == today and state.get("thin"):
            arts = arts[:2]
        return {n: [scraper.Article(i + 1, t, f"https://news.nate.com/view/{t}") for i, t in enumerate(arts)]
                for n in sections.values()}

    monkeypatch.setattr(scraper, "collect", fake_collect)
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

    # 12시: 오늘 랭킹 정상, 1차와 다른 기사는 모두 🆕
    state["thin"] = False
    state["titles"] = ["Y1", "A", "B", "C", "D", "E"]
    assert main.main(["news", "--edition", "noon", "--sections", "pol", "--out-dir", str(tmp_path)]) == 0
    md = sent[-1]
    assert "☀️ 2차 뉴스 브리핑" in md
    assert "view/Y1)** 🆕" not in md and "view/A)** 🆕" in md

    # 22시: 하루 정리 포함
    assert main.main(["news", "--edition", "evening", "--sections", "pol", "--out-dir", str(tmp_path)]) == 0
    assert overview_called and "오늘 하루 한눈에" in sent[-1]
    assert sorted(p.name for p in (tmp_path / "2026-11-12").iterdir()) == ["1-morning.md", "2-noon.md", "4-evening.md"]
