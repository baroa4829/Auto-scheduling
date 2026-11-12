"""네트워크 없이 스크래퍼/렌더링 흐름을 검증하는 테스트."""

import json
from datetime import date
from types import SimpleNamespace

import requests

from briefing_bot import notifier, scraper, summarizer


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

    md = notifier.render_markdown(date(2026, 11, 11), {"정치": arts}, {"정치": out})
    assert "## 정치" in md and "> 오늘의 흐름" in md and "   - 요약2" in md
    tg = notifier._telegram_messages(date(2026, 11, 11), {"정치": arts}, {"정치": out})
    assert len(tg) == 2 and "<b>■ 정치</b>" in tg[1]
