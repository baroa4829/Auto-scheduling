"""가족 알림: 네트워크 없이 iCal 파싱·분류·렌더링을 검증한다. (일정은 모두 가짜 데이터)"""

from datetime import date
from types import SimpleNamespace

from briefing_bot import family, kids, main

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:1
DTSTART:20270110T230000Z
DTEND:20270111T000000Z
SUMMARY:인테리어 중도금
DESCRIPTION:1000만원
END:VEVENT
BEGIN:VEVENT
UID:2
DTSTART;VALUE=DATE:20270204
DTEND;VALUE=DATE:20270205
SUMMARY:타일 시공
END:VEVENT
BEGIN:VEVENT
UID:3
DTSTART;TZID=Asia/Seoul:20270211T080000
DTEND;TZID=Asia/Seoul:20270211T090000
SUMMARY:이사
END:VEVENT
BEGIN:VEVENT
UID:4
DTSTART;VALUE=DATE:20270213
DTEND;VALUE=DATE:20270219
SUMMARY:가족 여행
END:VEVENT
BEGIN:VEVENT
UID:5
DTSTART;TZID=Asia/Seoul:20270205T100000
DTEND;TZID=Asia/Seoul:20270205T110000
SUMMARY:유치원 발표회
DESCRIPTION:준비물: 흰 티셔츠, 물통
END:VEVENT
BEGIN:VEVENT
UID:6
DTSTART;TZID=Asia/Seoul:20270101T080000
DTEND;TZID=Asia/Seoul:20270101T090000
RRULE:FREQ=MONTHLY
SUMMARY:곗돈
END:VEVENT
BEGIN:VEVENT
UID:7
DTSTART;VALUE=DATE:20270115
DTEND;VALUE=DATE:20270116
SUMMARY:이사 비선호
END:VEVENT
END:VCALENDAR
"""


def _events():
    return family.parse_ics(ICS, date(2027, 1, 1), date(2027, 3, 31))


def test_parse_ics_timezones_allday_and_recurrence():
    evs = {(e.title, e.start): e for e in _events()}
    pay = evs[("인테리어 중도금", date(2027, 1, 11))]  # UTC 23시 → KST 다음 날 08시
    assert pay.time == "08:00"
    trip = evs[("가족 여행", date(2027, 2, 13))]
    assert trip.end == date(2027, 2, 18) and trip.time == ""
    assert sum(1 for e in _events() if e.title == "곗돈") == 3  # 1·2·3월


def test_move_date_ignores_similar_titles():
    assert family.find_move_date(_events(), override="") == date(2027, 2, 11)
    assert family.find_move_date(_events(), override="2027-02-12") == date(2027, 2, 12)


def test_daily_plan_milestones_payments_phase_and_prep():
    evs = _events()
    move = date(2027, 2, 11)

    plan = family.build_plan(date(2027, 1, 4), evs, move)  # 중도금 D-7
    assert [(u.kind, u.days) for u in plan.upcoming] == [("payment", 7)]
    assert "1000만원" in family.render_daily(plan)

    plan = family.build_plan(date(2027, 2, 3), evs, move)  # 내일 타일, 모레 발표회 아님
    text = family.render_daily(plan)
    assert "타일 시공" in text and "두드려서" in text
    assert "D-8" in text

    plan = family.build_plan(date(2027, 2, 4), evs, move)  # 내일 발표회 + 준비물
    text = family.render_daily(plan)
    assert "🎒 준비물: 흰 티셔츠, 물통" in text

    plan = family.build_plan(date(2027, 2, 10), evs, move)  # 이사 D-1
    text = family.render_daily(plan)
    assert "이사까지 1일" in text and "이삿날 가방" in text

    plan = family.build_plan(date(2027, 2, 12), evs, move)  # 여행은 시작 전날에만
    assert [e.title for e in plan.tomorrow] == ["가족 여행"]
    plan = family.build_plan(date(2027, 2, 14), evs, move)
    assert plan.tomorrow == []
    assert "전입신고" not in family.render_daily(plan)


def test_empty_plan_is_skipped():
    plan = family.build_plan(date(2027, 6, 1), [], None)
    assert plan.is_empty()


def test_html_is_escaped():
    ev = family.CalEvent("<b>x</b> & 청소", date(2027, 1, 2), date(2027, 1, 2))
    text = family.render_daily(family.build_plan(date(2027, 1, 1), [ev], None))
    assert "&lt;b&gt;x&lt;/b&gt; &amp; 청소" in text


def test_watchlist_parsing():
    assert family.parse_watchlist("식세기:LG 식기세척기 14인용:1200000, 건조기") == [
        ("식세기", "LG 식기세척기 14인용", 1200000),
        ("건조기", "건조기", None),
    ]


def test_kid_stage_rolls_over_in_march():
    son, daughter = kids.parse_kids("첫째:남:2019,둘째:여:2021")
    assert son.stage(date(2026, 11, 13)).startswith("초등 1학년 (8세)")
    assert "3월에 2학년" in son.stage(date(2027, 1, 10))
    assert son.stage(date(2027, 3, 2)).startswith("초등 2학년")
    assert daughter.stage(date(2026, 11, 13)).startswith("유치원 만4세반 (6세)")
    assert "초등 입학" in daughter.stage(date(2027, 3, 2))


def test_run_family_never_writes_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAMILY_ICS_URLS", "https://example.invalid/basic.ics")
    monkeypatch.setattr(family, "fetch_events", lambda s, e: _events())
    monkeypatch.setattr(family, "fetch_prices", lambda w: [])
    monkeypatch.setattr(main, "now_kst", lambda: SimpleNamespace(date=lambda: date(2027, 2, 10)))
    rc = main.main(["family", "--edition", "daily", "--no-send", "--out-dir", str(tmp_path)])
    assert rc == 0
    assert "이사까지 1일" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []
