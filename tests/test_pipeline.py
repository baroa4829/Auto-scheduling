from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from autoscheduler.config import Settings
from autoscheduler.gcal import DryRunCalendar, build_event_body
from autoscheduler.models import ChatMessage, EventAction, ExtractionResult
from autoscheduler.pipeline import Scheduler
from autoscheduler.server import create_app
from autoscheduler.store import Store

TZ = ZoneInfo("Asia/Seoul")


class FakeExtractor:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def extract(self, messages, existing, source_label, room):
        self.calls.append((list(messages), list(existing)))
        return self.results.pop(0) if self.results else ExtractionResult(events=[])


def ev(**kw):
    base = dict(action="create", title="민수와 저녁", start="2026-11-11T19:00", end=None,
                all_day=False, location="강남역", status="confirmed", evidence="내일 7시")
    base.update(kw)
    return EventAction(**base)


def msg(text, minute=0, room="민수", source="kakao"):
    return ChatMessage(source, room, "민수", text, datetime(2026, 11, 10, 15, minute, tzinfo=TZ))


def make(results, **settings_kw):
    settings = Settings(webhook_token="t", **settings_kw)
    cal = DryRunCalendar()
    extractor = FakeExtractor(results)
    return Scheduler(settings, Store(":memory:"), extractor, cal), cal, extractor


def test_event_body_timed_default_hour():
    b = build_event_body("x", "2026-11-11T19:00", None, False, None, "d", "Asia/Seoul")
    assert b["start"] == {"dateTime": "2026-11-11T19:00:00", "timeZone": "Asia/Seoul"}
    assert b["end"]["dateTime"] == "2026-11-11T20:00:00"


def test_event_body_all_day_exclusive_end():
    b = build_event_body("x", "2026-11-11", None, True, None, "d", "Asia/Seoul")
    assert b["start"] == {"date": "2026-11-11"} and b["end"] == {"date": "2026-11-12"}


def test_create_then_duplicate_skipped():
    s, cal, _ = make([ExtractionResult(events=[ev()]), ExtractionResult(events=[ev()])])
    assert s.handle_message(msg("내일 저녁 7시 강남역?", 1)).created
    r = s.handle_message(msg("좋아 그때 봐", 2))
    assert not r.created and len(cal.created) == 1


def test_non_schedule_message_skips_llm():
    s, _, extractor = make([])
    s.handle_message(msg("ㅋㅋㅋ", 1))
    assert extractor.calls == []


def test_same_notification_twice_is_ignored():
    s, _, extractor = make([ExtractionResult(events=[])])
    m = msg("내일 7시?", 1)
    s.handle_message(m)
    assert s.handle_message(m).skipped == ["중복 메시지"]
    assert len(extractor.calls) == 1


def test_tentative_recorded_then_confirmed_creates():
    s, cal, _ = make([
        ExtractionResult(events=[ev(status="tentative")]),
        ExtractionResult(events=[ev(action="update", existing_event_id="1", status="confirmed")]),
    ])
    r1 = s.handle_message(msg("내일 7시 어때?", 1))
    assert not cal.created and r1.skipped
    r2 = s.handle_message(msg("좋아요 7시에 봐요", 2))
    assert r2.updated and len(cal.created) == 1
    assert cal.created[0]["summary"] == "민수와 저녁"


def test_update_and_cancel():
    s, cal, extractor = make([
        ExtractionResult(events=[ev()]),
        ExtractionResult(events=[ev(action="update", existing_event_id="1", start="2026-11-11T20:00")]),
        ExtractionResult(events=[ev(action="cancel", existing_event_id="1")]),
    ])
    s.handle_message(msg("내일 7시 확정", 1))
    s.handle_message(msg("8시로 바꿔도 돼?", 2))
    assert cal.updated[-1][1]["start"]["dateTime"] == "2026-11-11T20:00:00"
    assert extractor.calls[1][1][0].id == 1  # 기존 일정이 프롬프트에 전달됨
    s.handle_message(msg("미안 내일 취소하자", 3))
    assert cal.updated[-1][1]["summary"].startswith("[취소]")
    assert s.store.active_events("kakao", "민수") == []


def test_update_cannot_touch_other_room():
    s, cal, _ = make([
        ExtractionResult(events=[ev()]),
        ExtractionResult(events=[ev(action="cancel", existing_event_id="1")]),
    ])
    s.handle_message(msg("내일 7시", 1))
    r = s.handle_message(msg("내일 취소", 2, room="다른방"))
    assert r.skipped and not cal.updated


def test_import_chunks_by_room():
    s, cal, extractor = make([ExtractionResult(events=[ev()]), ExtractionResult(events=[])])
    msgs = [msg("내일 7시", 1), msg("토요일 2시", 2, room="철수")]
    r = s.import_messages(msgs)
    assert len(extractor.calls) == 2 and r.created


def test_webhook():
    s, cal, _ = make([ExtractionResult(events=[ev(title="당근 거래: 아이패드", location="역삼역")])])
    client = TestClient(create_app(s))
    body = {"app": "com.towneers.www", "title": "당근이", "text": "내일 저녁 7시 역삼역에서 거래 가능할까요?",
            "timestamp": "2026-11-10T15:00:00"}
    assert client.post("/webhook/notification", json=body).status_code == 401
    r = client.post("/webhook/notification", json=body, headers={"X-Auth-Token": "t"})
    assert r.status_code == 200 and r.json()["created"]
    assert s.store.active_events("daangn", "당근이")
    r = client.post("/webhook/notification?token=t", json={**body, "app": "com.other"})
    assert "ignored" in r.json()


def test_webhook_group_room_sender_split():
    s, _, extractor = make([ExtractionResult(events=[])])
    client = TestClient(create_app(s))
    client.post("/webhook/notification", headers={"X-Auth-Token": "t"},
                json={"app": "카카오톡", "title": "동창회", "room": "동창회", "text": "영희: 토요일 6시 어때"})
    m = extractor.calls[0][0][-1]
    assert (m.room, m.sender, m.text) == ("동창회", "영희", "토요일 6시 어때")


def test_webhook_query_params_with_quotes():
    s, _, extractor = make([ExtractionResult(events=[])])
    client = TestClient(create_app(s))
    r = client.post("/webhook/notification",
                    params={"token": "t", "app": "카카오톡", "title": "민수", "text": '내일 "7시" 어때'})
    assert r.status_code == 200
    assert extractor.calls[0][0][-1].text == '내일 "7시" 어때'


def test_webhook_form_body():
    s, _, extractor = make([ExtractionResult(events=[])])
    client = TestClient(create_app(s))
    r = client.post("/webhook/notification?token=t",
                    content="app=com.kakao.talk&title=%EB%AF%BC%EC%88%98&text=%EB%82%B4%EC%9D%BC+7%EC%8B%9C",
                    headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and extractor.calls[0][0][-1].text == "내일 7시"
