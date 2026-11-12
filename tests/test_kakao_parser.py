from zoneinfo import ZoneInfo

from autoscheduler.parsers.kakao_export import parse_kakao_export

TZ = ZoneInfo("Asia/Seoul")

ANDROID = """﻿민수 님과 카카오톡 대화
저장한 날짜 : 2026년 11월 12일 오전 9:00

2026년 11월 10일 화요일
2026년 11월 10일 오후 3:21, 민수 : 내일 저녁 7시에 강남역 어때?
2026년 11월 10일 오후 3:22, 나 : 좋아
그때 보자
2026년 11월 10일 오전 12:05, 민수 : 자정 테스트
"""

IOS = """민수 님과 카카오톡 대화
저장한 날짜 : 2026. 11. 12. 오전 9:00

2026. 11. 10. 15:21, 민수 : 토요일 2시?
2026. 11. 10. 오후 3:22, 나 : ㅇㅋ
"""

PC = """민수 님과 카카오톡 대화
저장한 날짜 : 2026-11-12 09:00:00

--------------- 2026년 11월 10일 화요일 ---------------
[민수] [오후 3:21] 내일 7시 어때
[나] [오후 3:22] 좋아요
"""


def test_android():
    msgs = parse_kakao_export(ANDROID, TZ)
    assert [m.sender for m in msgs] == ["민수", "나", "민수"]
    assert msgs[0].room == "민수"
    assert msgs[0].timestamp.hour == 15 and msgs[0].timestamp.minute == 21
    assert msgs[1].text == "좋아\n그때 보자"
    assert msgs[2].timestamp.hour == 0


def test_ios_mixed_clock():
    msgs = parse_kakao_export(IOS, TZ)
    assert [(m.sender, m.timestamp.hour) for m in msgs] == [("민수", 15), ("나", 15)]


def test_pc():
    msgs = parse_kakao_export(PC, TZ)
    assert len(msgs) == 2
    assert msgs[0].timestamp.isoformat() == "2026-11-10T15:21:00+09:00"
    assert msgs[1].text == "좋아요"


def test_system_lines_ignored():
    text = ANDROID + "2026년 11월 10일 오후 4:00, 철수님이 들어왔습니다.\n"
    msgs = parse_kakao_export(text, TZ)
    assert len(msgs) == 3
    assert "들어왔습니다" not in msgs[-1].text
