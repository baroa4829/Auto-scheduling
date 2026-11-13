"""이사·인테리어 일정 알림 (D-day 알림, 부부 공유 주간 리포트, 결제 알림, 이사날 날씨).

계획은 JSON 으로 적는다. 저장소가 공개일 수 있으므로 계획(날짜·금액·가족 일정)은 커밋하지 않는다.
  1) 환경변수 MOVING_PLAN (GitHub 저장소 Variables/Secrets 에 JSON 그대로 붙여넣기), 없으면
  2) MOVING_PLAN_FILE 경로의 파일 (기본: moving_plan.json, .gitignore 에 등록됨)

형식은 moving_plan.example.json 참고.
  - move_date: 이사일 (D-day 기준)
  - events: 날짜가 정해진 일정. amount(원) 가 있으면 결제 일정으로 보고 전날·당일에 금액과 함께 알린다.
            weather: true 면 전날·당일에 location 의 날씨를 붙인다.
  - checklist: 할 일. due 는 "D-30", "D+3" 또는 "2027-01-12". done: true 면 더 이상 알리지 않는다.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import requests

from . import weather

log = logging.getLogger(__name__)

WEEKDAYS = "월화수목금토일"
MILESTONES = {60, 30, 14, 7, 3, 2, 1, 0}
DUE_RE = re.compile(r"^D\s*([+-])\s*(\d+)$", re.IGNORECASE)


@dataclass
class Event:
    day: date
    title: str
    amount: int | None = None
    who: str = ""
    note: str = ""
    weather: bool = False


@dataclass
class Task:
    due: date
    task: str
    who: str = ""
    done: bool = False


@dataclass
class Plan:
    title: str
    move_date: date
    start_date: date
    end_date: date
    location: str = ""
    events: list[Event] = field(default_factory=list)
    checklist: list[Task] = field(default_factory=list)

    def dday(self, day: date) -> int:
        return (self.move_date - day).days

    def active(self, day: date) -> bool:
        return self.start_date <= day <= self.end_date


# ---------------- 계획 읽기 ----------------

def parse_due(value: str, move_date: date) -> date:
    value = str(value).strip()
    if m := DUE_RE.match(value):
        n = int(m.group(2))
        return move_date + timedelta(days=n if m.group(1) == "+" else -n)
    return date.fromisoformat(value)


def parse_plan(raw: dict) -> Plan:
    move = date.fromisoformat(raw["move_date"])
    start = date.fromisoformat(raw["start_date"]) if raw.get("start_date") else move - timedelta(days=60)
    end = move + timedelta(days=int(raw.get("end_after_days", 14)))
    events = [
        Event(
            day=date.fromisoformat(e["date"]),
            title=e["title"],
            amount=int(e["amount"]) if e.get("amount") else None,
            who=e.get("who", ""),
            note=e.get("note", ""),
            weather=bool(e.get("weather", False)),
        )
        for e in raw.get("events", [])
    ]
    tasks = [
        Task(parse_due(t["due"], move), t["task"], t.get("who", ""), bool(t.get("done", False)))
        for t in raw.get("checklist", [])
    ]
    events.sort(key=lambda e: e.day)
    tasks.sort(key=lambda t: t.due)
    return Plan(raw.get("title", "이사"), move, start, end, raw.get("location", ""), events, tasks)


def load_plan() -> Plan | None:
    """MOVING_PLAN 환경변수 → MOVING_PLAN_FILE 파일 순서로 찾는다. 둘 다 없으면 None."""
    text = (os.environ.get("MOVING_PLAN") or "").strip()
    if not text:
        path = Path(os.environ.get("MOVING_PLAN_FILE") or "moving_plan.json")
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
    try:
        return parse_plan(json.loads(text))
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        # 계획 내용이 로그(공개 저장소면 누구나 봄)에 남지 않도록 오류 종류만 남긴다
        raise ValueError(f"이사 계획(MOVING_PLAN) 형식이 올바르지 않습니다: {type(exc).__name__}") from None


# ---------------- 표시 도우미 ----------------

def fmt_amount(won: int) -> str:
    if won >= 10000 and won % 10000 == 0:
        return f"{won // 10000:,}만원"
    return f"{won:,}원"


def fmt_dday(n: int) -> str:
    if n > 0:
        return f"D-{n}"
    if n == 0:
        return "D-DAY"
    return f"D+{-n}"


def _day(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def _who(who: str) -> str:
    return f"[{who}] " if who else ""


def _event_line(e: Event, with_date: bool = False) -> str:
    head = f"{_day(e.day)} " if with_date else ""
    money = f" 💰 {fmt_amount(e.amount)}" if e.amount else ""
    note = f" — {e.note}" if e.note else ""
    return f"{head}{_who(e.who)}{e.title}{money}{note}"


def _task_line(t: Task, with_date: bool = True) -> str:
    head = f"~{_day(t.due)} " if with_date else ""
    return f"{head}{_who(t.who)}{t.task}"


def _esc_lines(lines: list[str], bullet: str = "•") -> list[str]:
    return [f"{bullet} {html.escape(x)}" for x in lines]


# ---------------- 날씨 ----------------

def _weather_line(plan: Plan, day: date, which: str) -> str | None:
    """which: 'today' | 'tomorrow'. location 이 없으면 WEATHER_LOCATIONS 첫 지역을 쓴다."""
    try:
        loc = weather.parse_locations(plan.location or None)[0]
        r = weather.analyze(loc, weather.fetch(loc))
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
        log.warning("이사 날씨 조회 실패: %s", type(exc).__name__)
        return None
    if which == "today":
        icon, desc = weather._wmo(r["day_code"])
        text = f"{icon} {loc.name} 오늘 {desc}, {r['tmin']}~{r['tmax']}°C, 강수확률 {r['rain_prob']}%"
        prob, tmin = r["rain_prob"], r["tmin"]
    else:
        t = r.get("tomorrow")
        if not t:
            return None
        icon, desc = weather._wmo(t["code"])
        text = f"{icon} {loc.name} 내일 {desc}, {t['tmin']}~{t['tmax']}°C, 강수확률 {t['rain_prob']}%"
        prob, tmin = t["rain_prob"], t["tmin"]
    tips = []
    if prob >= 50:
        tips.append("비·눈 예보: 이삿짐 방수 포장·바닥 보양을 업체에 요청하세요")
    if tmin <= -5:
        tips.append("한파: 세탁기·정수기 배관 동파 주의, 화분·약품은 차 안에 두지 마세요")
    return text + ("\n   " + "\n   ".join(tips) if tips else "")


# ---------------- 매일 알림 ----------------

def build_daily(plan: Plan, day: date, with_weather: bool = True) -> list[str] | None:
    """오늘 알릴 것이 없으면 None. (D-60/30/14/7/3/2/1/0 은 할 일이 없어도 보낸다)"""
    if not plan.active(day):
        return None
    tomorrow = day + timedelta(days=1)
    today_ev = [e for e in plan.events if e.day == day]
    tomorrow_ev = [e for e in plan.events if e.day == tomorrow]
    due_today = [t for t in plan.checklist if not t.done and t.due == day]
    overdue = [t for t in plan.checklist if not t.done and t.due < day]
    soon = [t for t in plan.checklist if not t.done and day < t.due <= day + timedelta(days=3)]
    dday = plan.dday(day)

    if not (today_ev or tomorrow_ev or due_today or overdue or dday in MILESTONES):
        return None

    buf = [f"🏠 <b>{html.escape(plan.title)} {fmt_dday(dday)}</b> — {_day(day)}"]
    if dday == 0:
        buf.append("오늘이 이사날입니다! 귀중품·서류·아이들 챙기고, 잔짐 확인 후 출발하세요 💪")

    pay_today = [e for e in today_ev if e.amount]
    pay_tomorrow = [e for e in tomorrow_ev if e.amount]
    if pay_today:
        buf += ["", f"💰 <b>오늘 결제</b> (합계 {fmt_amount(sum(e.amount for e in pay_today))})"]
        buf += _esc_lines([_event_line(e) for e in pay_today])
    if pay_tomorrow:
        buf += ["", f"💳 <b>내일 결제 준비</b> (합계 {fmt_amount(sum(e.amount for e in pay_tomorrow))}) — 이체 한도 확인"]
        buf += _esc_lines([_event_line(e) for e in pay_tomorrow])

    others_today = [e for e in today_ev if not e.amount]
    others_tomorrow = [e for e in tomorrow_ev if not e.amount]
    if others_today:
        buf += ["", "📅 <b>오늘 일정</b>"] + _esc_lines([_event_line(e) for e in others_today])
    if others_tomorrow:
        buf += ["", "⏰ <b>내일 일정</b>"] + _esc_lines([_event_line(e) for e in others_tomorrow])

    if due_today:
        buf += ["", "✅ <b>오늘까지 할 일</b>"] + _esc_lines([_task_line(t, False) for t in due_today], "☐")
    if overdue:
        buf += ["", f"⚠️ <b>기한 지난 할 일 {len(overdue)}개</b>"] + _esc_lines([_task_line(t) for t in overdue[:8]], "☐")
        if len(overdue) > 8:
            buf.append(f"… 외 {len(overdue) - 8}개")
    if soon and not due_today:
        buf += ["", "🔜 <b>사흘 안에 할 일</b>"] + _esc_lines([_task_line(t) for t in soon], "☐")

    if with_weather:
        lines = []
        if any(e.weather for e in today_ev) and (w := _weather_line(plan, day, "today")):
            lines.append(w)
        if any(e.weather for e in tomorrow_ev) and (w := _weather_line(plan, day, "tomorrow")):
            lines.append(w)
        if lines:
            buf += ["", "🌤️ <b>날씨</b>"] + [html.escape(x) for x in lines]

    return ["\n".join(buf)[:4000]]


# ---------------- 주간 리포트 ----------------

def build_weekly(plan: Plan, day: date, horizon: int = 14) -> list[str] | None:
    """앞으로 horizon 일 일정·결제·할 일과 진행률. 활성 기간이 아니면 None."""
    if not plan.active(day):
        return None
    until = day + timedelta(days=horizon)
    upcoming = [e for e in plan.events if day <= e.day <= until]
    payments = [e for e in upcoming if e.amount]
    todo = [t for t in plan.checklist if not t.done and day <= t.due <= until]
    overdue = [t for t in plan.checklist if not t.done and t.due < day]
    total = len(plan.checklist)
    done = sum(t.done for t in plan.checklist)

    buf = [
        f"📋 <b>{html.escape(plan.title)} 주간 리포트</b> — {_day(day)} ({fmt_dday(plan.dday(day))})",
        f"이사일 {_day(plan.move_date)} · 체크리스트 {done}/{total} 완료",
    ]
    if upcoming:
        buf += ["", f"📅 <b>앞으로 {horizon}일 일정</b>"] + _esc_lines([_event_line(e, True) for e in upcoming])
    else:
        buf += ["", f"📅 앞으로 {horizon}일 동안 등록된 일정이 없습니다"]
    if payments:
        buf += ["", f"💰 <b>결제 예정 합계 {fmt_amount(sum(e.amount for e in payments))}</b>"]
        buf += _esc_lines([f"{_day(e.day)} {e.title} {fmt_amount(e.amount)}" for e in payments])
    if todo:
        buf += ["", "☑️ <b>이번 2주 할 일</b> (담당 확인해 주세요)"] + _esc_lines([_task_line(t) for t in todo], "☐")
    if overdue:
        buf += ["", f"⚠️ <b>기한 지난 할 일 {len(overdue)}개</b>"] + _esc_lines([_task_line(t) for t in overdue], "☐")
    buf += ["", "다 한 일은 MOVING_PLAN 에서 \"done\": true 로 바꾸면 알림에서 빠집니다."]
    return ["\n".join(buf)[:4000]]


def chat_ids() -> list[str]:
    """MOVE_TELEGRAM_CHAT_ID (쉼표로 여러 개, 부부 단톡방 ID 등) → 없으면 TELEGRAM_CHAT_ID."""
    raw = os.environ.get("MOVE_TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or ""
    return [c.strip() for c in raw.split(",") if c.strip()]
