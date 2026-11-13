"""가족 일정 비서: Google 캘린더(iCal 비공개 주소)를 읽어 텔레그램으로 알려 준다.

이 저장소는 공개 저장소라서 가족 일정은 저장소에 두지 않는다.
- 일정은 Secret `FAMILY_ICS_URLS` (iCal 비공개 주소, 쉼표로 여러 개)에서 실행할 때마다 읽는다.
- 결과는 텔레그램으로만 보내고 briefings/ 에 저장하거나 로그에 내용을 찍지 않는다.
  (공개 저장소의 Actions 로그와 커밋은 누구나 볼 수 있다)

매일 저녁 알림(daily)에 들어가는 것:
    🏠 이사 D-day 와 그날 할 일          캘린더의 '이사' 일정 기준 (FAMILY_MOVE_DATE 로 덮어쓰기 가능)
    📅 내일 일정 + 준비물               일정 설명에 '준비물: ...' 이라고 적으면 따로 뽑아 준다
    🔨 인테리어 공정 체크포인트          제목에 철거·설비·방수·전기·목공·타일·도배·마루 등이 있으면
    💰 큰 돈 나가는 날 D-7 / D-3 / D-1   착수금·중도금·잔금·계약금 등
    🏫 학교·유치원 행사 D-7 / D-3
    🩺 접종·검진·병원 D-3
    🛒 가전 최저가 (APPLIANCE_WATCHLIST 와 네이버 쇼핑 API 키가 있을 때만)
"""

from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import requests

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
WEEKDAYS = "월화수목금토일"


# ---------------- 캘린더 읽기 ----------------

@dataclass
class CalEvent:
    title: str
    start: date  # KST 날짜
    end: date  # 마지막 날 (포함)
    time: str = ""  # "14:00" (종일 일정이면 빈 문자열)
    description: str = ""
    location: str = ""

    def covers(self, day: date) -> bool:
        return self.start <= day <= self.end


def _to_kst(value) -> tuple[date, str]:
    if isinstance(value, datetime):
        if value.tzinfo is None:  # 시간대 없는 일정은 한국 시간으로 본다
            value = value.replace(tzinfo=KST)
        value = value.astimezone(KST)
        return value.date(), f"{value:%H:%M}"
    return value, ""


def parse_ics(text: str | bytes, start: date, end: date) -> list[CalEvent]:
    """iCal 텍스트에서 [start, end] 사이 일정을 반복 일정까지 펼쳐서 돌려준다."""
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(text)
    out = []
    for comp in recurring_ical_events.of(cal).between(start, end + timedelta(days=1)):
        s_day, s_time = _to_kst(comp.get("DTSTART").dt)
        dtend = comp.get("DTEND")
        if dtend is None:
            e_day = s_day
        else:
            e_day, e_time = _to_kst(dtend.dt)
            # 종일 일정의 DTEND 는 다음 날 0시(포함 안 함), 시간 일정은 0시에 끝나면 전날까지
            if (not s_time and e_day > s_day) or (s_time and e_time == "00:00" and e_day > s_day):
                e_day -= timedelta(days=1)
        out.append(CalEvent(
            title=str(comp.get("SUMMARY", "")).strip(),
            start=s_day,
            end=max(e_day, s_day),
            time=s_time,
            description=str(comp.get("DESCRIPTION", "") or "").strip(),
            location=str(comp.get("LOCATION", "") or "").strip(),
        ))
    out.sort(key=lambda e: (e.start, e.time or "00:00", e.title))
    return out


def fetch_events(start: date, end: date, urls: str | None = None) -> list[CalEvent]:
    urls = urls if urls is not None else os.environ.get("FAMILY_ICS_URLS", "")
    events: list[CalEvent] = []
    seen = set()
    for i, url in enumerate(u.strip() for u in urls.split(",") if u.strip()):
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            evs = parse_ics(resp.content, start, end)
        except Exception as exc:  # noqa: BLE001 - 주소는 비밀값이라 로그에 남기지 않는다
            log.error("캘린더 %d번 주소를 읽지 못했습니다: %s", i + 1, type(exc).__name__)
            continue
        for e in evs:  # 같은 일정이 여러 캘린더에 있으면 한 번만
            key = (e.title, e.start, e.time)
            if key not in seen:
                seen.add(key)
                events.append(e)
    events.sort(key=lambda e: (e.start, e.time or "00:00", e.title))
    return events


# ---------------- 분류 규칙 ----------------

BIG_PAYMENT_RE = re.compile(r"착수금|중도금|잔금|계약금|대금|취득세|양도세|등기")
SCHOOL_RE = re.compile(
    r"학교|유치원|어린이집|방과후|방학|개학|입학|졸업|상담|체험학습|현장학습|소풍|발표회|"
    r"공개수업|학예회|운동회|대회|원서|등록"
)
HEALTH_RE = re.compile(r"접종|검진|병원|치과|소아과|안과|이비인후과|피부과|건강검진")
MOVE_RE = re.compile(r"이사|입주|가전|커튼|커텐|소파|식탁|침대|사전방문|청소|에어컨|인테리어|공사")
MOVE_DAY_RE = re.compile(r"^\s*(이사|이삿날|이사일|이사하는 날)\s*$")
PREP_RE = re.compile(r"준비물\s*[:：]?\s*(.+)")

# 인테리어 공정별 체크포인트 (#3). 덮이기 전에 사진을 남겨야 하는 공정이 많다.
PHASES: list[tuple[str, str, list[str]]] = [
    ("철거", r"철거", [
        "남길 것(문·몰딩·붙박이장 등)에 표시했는지",
        "엘리베이터·공용부 보양, 관리사무소 공사 신고·동의서",
    ]),
    ("설비·배관", r"설비|배관|수도", [
        "바닥·벽 배관 위치를 줄자 대고 사진으로 (덮이면 못 봄)",
        "수압·누수 테스트 입회",
    ]),
    ("방수", r"방수", [
        "방수층 사진, 담수 테스트(24~48시간) 결과 확인",
        "욕실·베란다 배수구 쪽 경사(구배)",
    ]),
    ("전기", r"전기|전열|전등|배선|조명", [
        "콘센트·스위치 위치가 도면과 같은지 (침대 옆, TV, 식탁, 공부방 책상)",
        "인덕션·건조기·식기세척기 전용 회로",
        "벽 덮기 전 배선 사진",
    ]),
    ("목공", r"목공|천장|몰딩|붙박이", [
        "커튼박스 깊이·폭 (커튼·블라인드 주문 치수와 맞는지)",
        "붙박이장·냉장고장 안쪽 치수 = 가전 실제 치수 + 여유",
    ]),
    ("타일", r"타일|욕실", [
        "두드려서 들뜬 소리 나는 곳, 줄눈 색",
        "물 부어서 배수구로 잘 빠지는지",
    ]),
    ("도배", r"도배|벽지", [
        "이음매·들뜸, 콘센트 주변 마감",
        "도배 후 2~3일은 창문 조금만 열기 (급격한 건조는 들뜸 원인)",
    ]),
    ("바닥", r"마루|바닥|장판|강마루", [
        "걸을 때 삐걱·들뜸, 걸레받이 틈",
        "방문 아래가 바닥에 걸리지 않는지",
    ]),
    ("필름", r"필름", ["기포·모서리 들뜸"]),
    ("탄성코트", r"탄성\s*코트", [
        "베란다 곰팡이·결로 자국을 먼저 제거했는지",
        "칠한 뒤 하루 이틀은 베란다 창문 열어 건조",
    ]),
    ("욕실 기구", r"기구\s*셋팅|기구\s*세팅|도기|수전", [
        "수전 온수·냉수 방향, 샤워기 수압",
        "변기·세면대 아래 누수, 흔들림",
        "휴지걸이·수건걸이 높이 (아이 손 닿는 곳)",
    ]),
    ("중문·도어", r"중문|도어|방문", [
        "슬라이딩 중문 레일 소리·걸림, 닫힐 때 손끼임 방지",
        "방문 닫힘·잠금, 문 아래 바닥과 간격",
    ]),
    ("실리콘", r"실리콘", [
        "욕실·주방 실리콘 끊긴 곳, 색",
        "굳는 동안 24시간은 물 쓰지 말고 환기",
    ]),
    ("주방·가구", r"주방|싱크|가구|상판", [
        "상판 수평, 문짝 단차, 하부장 배관 누수",
        "식기세척기·인덕션·냉장고 자리 치수 재확인",
    ]),
    ("시스템에어컨", r"시스템\s*에어컨|에어컨", [
        "배수(드레인) 테스트, 실외기 위치·배관 마감",
        "실별 리모컨·컨트롤러 동작",
    ]),
    ("입주청소", r"입주\s*청소|청소", [
        "모든 공정이 끝난 뒤인지 (공사 먼지 재발생)",
        "창틀 레일, 욕실 줄눈, 붙박이장 안, 환풍기·후드 필터",
    ]),
    ("마감·하자점검", r"마감|준공|하자|점검", [
        "하자 목록을 사진과 함께 업체에 문서로 전달",
        "잔금 전에 하자 보수 일정 확정, A/S 기간 서면으로 받기",
    ]),
]

# 이사 D-day 별 할 일 (#1). 키: 이사일까지 남은 날 (음수 = 이사 후)
MOVE_MILESTONES: dict[int, list[str]] = {
    45: ["이사업체 견적 3곳 받기 (방문 견적, 사다리차·보관 여부 포함)"],
    30: [
        "이사업체 계약, 엘리베이터 사용 예약 (두 집 모두)",
        "버릴 가구·가전: 대형폐기물 신고 / 당근 판매 시작",
        "인터넷·TV 이전 설치 신청",
    ],
    21: [
        "전학·유치원 이동 서류 확인, 새 동네 학원 상담",
        "우체국 '주거이전 우편물 전송 서비스' 신청",
    ],
    14: [
        "가전·가구 배송 시간대 확정 (같은 날이면 순서: 커튼 → 가전 → 가구)",
        "도시가스 연결 예약 (새집), 관리비·공과금 정산 예약 (헌집)",
    ],
    7: [
        "짐 분류 마무리: 버릴 것 / 가져갈 것 / 내가 직접 옮길 것",
        "이삿날 아이 돌봄·반려동물 맡길 곳 확정",
        "귀중품·서류·노트북은 따로 챙길 가방에",
    ],
    3: [
        "냉장고 비우기 시작, 세탁기 물빼기 방법 확인",
        "이사업체에 시간·주소·주차 최종 확인 전화",
    ],
    1: [
        "이삿날 가방: 서류, 충전기, 상비약, 아이 간식·장난감, 휴지·수건, 현금",
        "새집 상태 사진 (이삿짐 들어가기 전)",
        "가구 배치도 출력 또는 사진으로 준비",
    ],
    0: [
        "헌집: 빈 집 사진, 전기·수도·가스 계량기 사진",
        "새집: 바닥 보양 확인, 가구 배치 지시, 파손 즉시 사진",
    ],
    -1: [
        "전입신고 (정부24 온라인, 14일 이내)",
        "파인 '금융주소 한번에'로 은행·카드·보험 주소 일괄 변경",
    ],
    -7: ["택배·쇼핑몰·배달앱 기본 주소 변경", "하자 1차 점검 (문·창문·수전·배수)"],
    -14: ["전입신고 마감일 (안 했으면 오늘까지)"],
    -30: ["반려동물 등록 주소 변경 신고 기한 (30일 이내)", "하자 2차 점검 후 업체에 목록 전달"],
}


def find_move_date(events: list[CalEvent], override: str | None = None) -> date | None:
    override = override if override is not None else os.environ.get("FAMILY_MOVE_DATE", "")
    if override.strip():
        return datetime.strptime(override.strip(), "%Y-%m-%d").date()
    for e in events:
        if MOVE_DAY_RE.match(e.title):
            return e.start
    return None


def phase_checks(title: str) -> list[tuple[str, list[str]]]:
    return [(name, items) for name, pat, items in PHASES if re.search(pat, title)]


def prep_items(e: CalEvent) -> list[str]:
    out = []
    for line in (e.description or "").splitlines():
        m = PREP_RE.search(line)
        if m:
            out += [x.strip() for x in re.split(r"[,，·/]", m.group(1)) if x.strip()]
    return out


@dataclass
class Upcoming:
    days: int
    event: CalEvent
    kind: str  # payment / school / health / move


@dataclass
class DailyPlan:
    today: date
    move_date: date | None
    tomorrow: list[CalEvent] = field(default_factory=list)
    upcoming: list[Upcoming] = field(default_factory=list)
    milestone: list[str] = field(default_factory=list)
    prices: list[dict] = field(default_factory=list)

    @property
    def move_days(self) -> int | None:
        return (self.move_date - self.today).days if self.move_date else None

    def is_empty(self) -> bool:
        show_dday = self.move_days is not None and -30 <= self.move_days <= 60
        return not (self.tomorrow or self.upcoming or self.milestone or self.prices or show_dday)


UPCOMING_RULES: list[tuple[str, re.Pattern, tuple[int, ...]]] = [
    ("payment", BIG_PAYMENT_RE, (7, 3)),
    ("school", SCHOOL_RE, (7, 3)),
    ("health", HEALTH_RE, (3,)),
    ("move", MOVE_RE, (7, 3)),
]


def build_plan(today: date, events: list[CalEvent], move_date: date | None) -> DailyPlan:
    tomorrow = today + timedelta(days=1)
    plan = DailyPlan(today=today, move_date=move_date)
    # 여러 날 일정(여행 등)은 시작하는 날에만 보여 준다
    plan.tomorrow = [e for e in events if e.start == tomorrow]
    seen = set()
    for e in events:
        days = (e.start - today).days
        if e.title.startswith("[공사]"):  # 공정은 전날 체크포인트로만 알린다 (매번 D-7 은 너무 많음)
            continue
        for kind, pat, offsets in UPCOMING_RULES:
            if days in offsets and pat.search(e.title) and id(e) not in seen:
                seen.add(id(e))
                plan.upcoming.append(Upcoming(days, e, kind))
    if move_date:
        plan.milestone = MOVE_MILESTONES.get((move_date - today).days, [])
    return plan


# ---------------- 가전 최저가 (#8) ----------------

def parse_watchlist(spec: str | None = None) -> list[tuple[str, str, int | None]]:
    """'이름:검색어:목표가,...' (목표가는 생략 가능)."""
    spec = spec if spec is not None else os.environ.get("APPLIANCE_WATCHLIST", "")
    out = []
    for item in (x.strip() for x in spec.split(",") if x.strip()):
        parts = [p.strip() for p in item.split(":")]
        name, query = parts[0], parts[1] if len(parts) > 1 and parts[1] else parts[0]
        target = int(re.sub(r"\D", "", parts[2])) if len(parts) > 2 and re.sub(r"\D", "", parts[2]) else None
        out.append((name, query, target))
    return out


def fetch_prices(watchlist: list[tuple[str, str, int | None]]) -> list[dict]:
    cid, secret = os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET")
    if not (watchlist and cid and secret):
        return []
    out = []
    for name, query, target in watchlist:
        try:
            resp = requests.get(
                "https://openapi.naver.com/v1/search/shop.json",
                params={"query": query, "display": 20, "sort": "sim", "exclude": "used:rental:cbshop"},
                headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret},
                timeout=15,
            )
            resp.raise_for_status()
            items = [i for i in resp.json().get("items", []) if str(i.get("lprice", "")).isdigit()]
        except (requests.RequestException, ValueError) as exc:
            log.warning("가전 가격 조회 실패 (%s): %s", name, type(exc).__name__)
            continue
        if not items:
            continue
        best = min(items, key=lambda i: int(i["lprice"]))
        out.append({
            "name": name,
            "price": int(best["lprice"]),
            "mall": best.get("mallName", ""),
            "link": best.get("link", ""),
            "target": target,
        })
    return out


# ---------------- 렌더링 ----------------

def _d(days: int) -> str:
    return "D-day" if days == 0 else (f"D-{days}" if days > 0 else f"D+{-days}")


def _day(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


KIND_EMOJI = {"payment": "💰", "school": "🏫", "health": "🩺", "move": "🏠"}


def _event_emoji(e: CalEvent) -> str:
    t = e.title
    if BIG_PAYMENT_RE.search(t):
        return "💰"
    if phase_checks(t):
        return "🔨"
    if SCHOOL_RE.search(t):
        return "🏫"
    if HEALTH_RE.search(t):
        return "🩺"
    if MOVE_RE.search(t):
        return "🏠"
    return "•"


def render_daily(plan: DailyPlan) -> str:
    esc = html.escape
    tomorrow = plan.today + timedelta(days=1)
    lines = [f"👨‍👩‍👧‍👦 <b>가족 일정 · 내일 {_day(tomorrow)}</b>"]

    md = plan.move_days
    if md is not None and -30 <= md <= 60:
        label = "이사까지" if md > 0 else ("오늘 이사!" if md == 0 else "이사한 지")
        count = f"{md}일" if md > 0 else ("" if md == 0 else f"{-md}일째")
        lines += ["", f"🏠 <b>{label} {count}</b> ({_d(md)}, {_day(plan.move_date)})".replace("  ", " ")]
        if plan.milestone:
            lines += [f"☐ {esc(x)}" for x in plan.milestone]

    lines += ["", "📅 <b>내일 일정</b>"]
    if not plan.tomorrow:
        lines.append("없음")
    for e in plan.tomorrow:
        when = f"{e.time} " if e.time else ""
        span = f" (~{_day(e.end)})" if e.end > e.start else ""
        where = f" @{esc(e.location)}" if e.location else ""
        lines.append(f"{_event_emoji(e)} {when}{esc(e.title)}{span}{where}")
        if BIG_PAYMENT_RE.search(e.title) and e.description:
            lines.append(f"   └ {esc(e.description.splitlines()[0][:60])}")
        if prep := prep_items(e):
            lines.append(f"   🎒 준비물: {esc(', '.join(prep))}")
        for name, items in phase_checks(e.title):
            lines.append(f"   🔨 {esc(name)} 체크")
            lines += [f"   ☐ {esc(x)}" for x in items]

    if plan.upcoming:
        lines += ["", "⏰ <b>다가오는 일정</b>"]
        for u in sorted(plan.upcoming, key=lambda u: u.days):
            extra = ""
            if u.kind == "payment" and u.event.description:
                extra = f" · {esc(u.event.description.splitlines()[0][:40])}"
            lines.append(f"{KIND_EMOJI[u.kind]} {_d(u.days)} {_day(u.event.start)} {esc(u.event.title)}{extra}")
            if prep := prep_items(u.event):
                lines.append(f"   🎒 준비물: {esc(', '.join(prep))}")

    if plan.prices:
        lines += ["", "🛒 <b>가전 최저가</b> (네이버 쇼핑)"]
        for p in plan.prices:
            hit = " 🎯 목표가 도달!" if p["target"] and p["price"] <= p["target"] else ""
            goal = f" / 목표 {p['target']:,}원" if p["target"] else ""
            link = f'<a href="{esc(p["link"])}">{esc(p["name"])}</a>' if p["link"] else esc(p["name"])
            lines.append(f"• {link} {p['price']:,}원 ({esc(p['mall'])}){goal}{hit}")

    return "\n".join(lines)[:4000]


def build_daily(today: date) -> str | None:
    """매일 저녁 가족 알림. 보낼 내용이 없으면 None."""
    events = fetch_events(today - timedelta(days=60), today + timedelta(days=90))
    plan = build_plan(today, events, find_move_date(events))
    plan.prices = fetch_prices(parse_watchlist())
    if plan.is_empty():
        return None
    return render_daily(plan)
