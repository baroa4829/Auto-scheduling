"""아이들 관련 주간 알림.

- weekend (금 18시): 주말 날씨 + 캘린더 빈 시간 기준 아이 나들이 추천 (#25)
- study   (일 19시): 이번 주 학습지·퀴즈 (#27). 정답은 텔레그램 스포일러로 가린다.

아이 정보는 Variable `FAMILY_KIDS` 에 '호칭:성별:출생연도' 를 쉼표로 적는다.
    예) 첫째:남:2019,둘째:여:2021
공개 저장소이므로 이름 대신 '첫째/둘째' 같은 호칭을 권한다.
"""

from __future__ import annotations

import html
import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta

import requests

from . import family, weather

log = logging.getLogger(__name__)


# ---------------- 아이 정보 ----------------

@dataclass
class Kid:
    label: str
    sex: str
    birth_year: int

    def stage(self, today: date) -> str:
        school_year = today.year if today.month >= 3 else today.year - 1  # 학년은 3월에 바뀐다
        grade = school_year - (self.birth_year + 7) + 1
        korean_age = today.year - self.birth_year + 1
        if grade >= 1:
            s = f"초등 {grade}학년 ({korean_age}세)"
            if today.month in (12, 1, 2):
                s += f", 3월에 {grade + 1}학년 진급 예정"
            return s
        cls = school_year - self.birth_year - 1
        s = f"유치원 만{cls}세반 ({korean_age}세)"
        if grade == 0:
            s += ", 다음 3월 초등 입학 예정"
        return s

    def describe(self, today: date) -> str:
        sex = {"남": "아들", "여": "딸"}.get(self.sex, "아이")
        return f"{self.label}({sex}): {self.stage(today)}"


def parse_kids(spec: str | None = None) -> list[Kid]:
    spec = spec if spec is not None else os.environ.get("FAMILY_KIDS", "")
    kids = []
    for item in (x.strip() for x in spec.split(",") if x.strip()):
        parts = [p.strip() for p in item.split(":")]
        if len(parts) == 3 and parts[2].isdigit():
            kids.append(Kid(parts[0], parts[1], int(parts[2])))
        else:
            log.warning("FAMILY_KIDS 형식이 아닙니다 (호칭:성별:출생연도): %s", item)
    return kids


def _ask(system: str, schema: dict, content: str, label: str) -> dict:
    import anthropic

    from .summarizer import _ask_json

    return _ask_json(anthropic.Anthropic(), system, schema, content, label)


# ---------------- 주말 나들이 (#25) ----------------

def home_location() -> weather.Location:
    spec = os.environ.get("FAMILY_HOME")
    return weather.parse_locations(spec)[0]


def weekend_forecast(loc: weather.Location, days: list[date]) -> list[dict]:
    resp = requests.get(
        weather.FORECAST_URL,
        params={
            "latitude": loc.lat, "longitude": loc.lon, "timezone": "Asia/Seoul",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "start_date": days[0].isoformat(), "end_date": days[-1].isoformat(),
        },
        timeout=15,
    )
    resp.raise_for_status()
    d = resp.json()["daily"]
    out = []
    for i, day in enumerate(days):
        emoji, desc = weather._wmo(d["weather_code"][i])
        out.append({
            "day": day, "emoji": emoji, "desc": desc,
            "tmin": round(d["temperature_2m_min"][i]), "tmax": round(d["temperature_2m_max"][i]),
            "rain": d["precipitation_probability_max"][i] or 0,
        })
    return out


OUTING_PROMPT = """\
당신은 한국 수도권에 사는 가족의 주말 나들이 플래너입니다.
아이 정보, 집 위치, 주말 날씨, 이미 잡힌 가족 일정을 보고 이번 주말 나들이를 추천합니다.

규칙:
- 이미 일정이 있는 시간은 피하고, 여행처럼 집을 비우는 일정이 있으면 그날은 추천하지 않습니다.
- 집에서 차로 1시간 이내, 두 아이가 함께 즐길 수 있는 곳을 고릅니다.
- 실제로 잘 알려진 장소만 고르고, 확실하지 않은 장소는 지어내지 않습니다.
- 비·눈 확률 50% 이상이거나 영하 5도 이하면 실내 위주로 추천합니다.
- picks 는 2~4개. when 은 '토 오전', '일 오후' 같은 형식.
- tip 에는 준비물이나 주차·예약 팁을 한 문장으로 씁니다.
- note 에는 주말 전체 한 줄 요약(날씨·일정 고려)을 씁니다.
"""

OUTING_SCHEMA = {
    "type": "object",
    "properties": {
        "note": {"type": "string"},
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "when": {"type": "string"},
                    "name": {"type": "string"},
                    "area": {"type": "string"},
                    "indoor": {"type": "boolean"},
                    "why": {"type": "string"},
                    "tip": {"type": "string"},
                },
                "required": ["when", "name", "area", "indoor", "why", "tip"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["note", "picks"],
    "additionalProperties": False,
}


def build_weekend(today: date) -> str:
    sat = today + timedelta(days=(5 - today.weekday()) % 7)
    days = [sat, sat + timedelta(days=1)]
    loc = home_location()
    fc = weekend_forecast(loc, days)
    events = [e for e in family.fetch_events(days[0] - timedelta(days=7), days[1])
              if e.start <= days[1] and e.end >= days[0]]
    kids = parse_kids()

    content = "\n".join(
        ["[아이]"] + [k.describe(today) for k in kids] + (["(정보 없음: 초등 저학년·유치원생 가정)"] if not kids else [])
        + ["", f"[집 근처] {loc.name}"]
        + ["", "[주말 날씨]"]
        + [f"- {family._day(f['day'])} {f['desc']} {f['tmin']}~{f['tmax']}도, 강수확률 {f['rain']}%" for f in fc]
        + ["", "[이미 잡힌 일정]"]
        + ([f"- {family._day(e.start)}{'~' + family._day(e.end) if e.end > e.start else ''} "
            f"{e.time} {e.title}" for e in events] or ["- 없음"])
    )
    res = _ask(OUTING_PROMPT, OUTING_SCHEMA, content, "outing")

    esc = html.escape
    lines = [f"🎈 <b>주말 나들이 추천</b> · {family._day(days[0])}~{family._day(days[1])}", ""]
    lines += [f"{f['emoji']} {family._day(f['day'])} {f['desc']} {f['tmin']}°/{f['tmax']}° ☔{f['rain']}%" for f in fc]
    if events:
        lines += ["", "📅 " + ", ".join(esc(e.title) for e in events)]
    lines += ["", f"<i>{esc(res['note'])}</i>"]
    for p in res["picks"]:
        lines += [
            "",
            f"{'🏠' if p['indoor'] else '🌳'} <b>{esc(p['when'])} · {esc(p['name'])}</b> ({esc(p['area'])})",
            f"   {esc(p['why'])}",
            f"   💡 {esc(p['tip'])}",
        ]
    lines += ["", "<i>※ 방문 전 운영 시간·휴무일을 꼭 확인하세요.</i>"]
    return "\n".join(lines)[:4000]


# ---------------- 주간 학습지 (#27) ----------------

STUDY_PROMPT = """\
당신은 초등 저학년과 유치원생을 가르치는 다정한 선생님입니다.
아이별 발달 단계에 맞는 '이번 주 학습지'를 만듭니다. 부모가 텔레그램으로 받아 저녁에 함께 풀어 봅니다.

규칙:
- 초등학생: 학년 교육과정 수준의 수학 4문제 + 받아쓰기 낱말·문장 4개 + 생각해 보기 1문제.
  12~2월에는 지난 학년 복습과 다음 학년 예습을 섞습니다.
- 유치원생: 한글(글자 찾기·첫소리) 2문제, 수 세기·비교 2문제, 놀이형 1문제.
  그림이 없어도 말로 할 수 있게 냅니다.
- 문제는 짧고 구체적으로. 답(a)은 한 줄로.
- 계절·명절 같은 이번 주 소재를 활용하면 좋습니다.
- parent_tip 은 부모에게 주는 한 문장 학습 팁입니다.
"""

STUDY_SCHEMA = {
    "type": "object",
    "properties": {
        "kids": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "theme": {"type": "string"},
                    "problems": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"q": {"type": "string"}, "a": {"type": "string"}},
                            "required": ["q", "a"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["label", "theme", "problems"],
                "additionalProperties": False,
            },
        },
        "parent_tip": {"type": "string"},
    },
    "required": ["kids", "parent_tip"],
    "additionalProperties": False,
}


def build_study(today: date) -> list[str]:
    kids = parse_kids()
    if not kids:
        raise RuntimeError("FAMILY_KIDS 변수가 비어 있습니다 (예: 첫째:남:2019,둘째:여:2021)")
    content = f"오늘: {today:%Y-%m-%d}\n" + "\n".join(k.describe(today) for k in kids)
    res = _ask(STUDY_PROMPT, STUDY_SCHEMA, content, "study")

    esc = html.escape
    msgs = []
    for k in res["kids"]:
        lines = [f"✏️ <b>{esc(k['label'])} 이번 주 학습지</b> · {esc(k['theme'])}", ""]
        for i, p in enumerate(k["problems"], 1):
            lines.append(f"{i}. {esc(p['q'])}")
        lines += ["", "<b>정답</b> (눌러서 보기)"]
        lines += [f"{i}. <tg-spoiler>{esc(p['a'])}</tg-spoiler>" for i, p in enumerate(k["problems"], 1)]
        msgs.append("\n".join(lines)[:4000])
    if msgs:
        msgs[-1] += f"\n\n💡 {esc(res['parent_tip'])}"
    return msgs

