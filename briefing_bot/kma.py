"""기상청 단기예보(공공데이터포털 '기상청_단기예보 조회서비스')를 Open-Meteo 응답 모양으로 바꿔 준다.

동네(5km 격자) 단위 예보라 한국 지역은 이 소스가 가장 정확하다. 인증키는 GitHub Secret KMA_API_KEY.
https://www.data.go.kr/data/15084084/openapi.do
"""

from __future__ import annotations

import math
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

from .metno import _feels_like

URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
KST = timezone(timedelta(hours=9))
BASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)  # 단기예보 발표 시각 (발표 후 약 10분 뒤부터 조회 가능)


def api_key() -> str | None:
    return (os.environ.get("KMA_API_KEY") or "").strip() or None


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """위경도 → 기상청 격자(nx, ny). 기상청 Lambert 정각원추도법 공식."""
    earth_r, grid = 6371.00877, 5.0
    slat1, slat2, olon, olat, xo, yo = 30.0, 60.0, 126.0, 38.0, 43, 136
    deg = math.pi / 180.0
    re_g = earth_r / grid
    s1, s2, ol, oa = slat1 * deg, slat2 * deg, olon * deg, olat * deg
    sn = math.log(math.cos(s1) / math.cos(s2)) / math.log(
        math.tan(math.pi * 0.25 + s2 * 0.5) / math.tan(math.pi * 0.25 + s1 * 0.5)
    )
    sf = math.tan(math.pi * 0.25 + s1 * 0.5) ** sn * math.cos(s1) / sn
    ro = re_g * sf / math.tan(math.pi * 0.25 + oa * 0.5) ** sn
    ra = re_g * sf / math.tan(math.pi * 0.25 + lat * deg * 0.5) ** sn
    theta = lon * deg - ol
    theta = (theta + math.pi) % (2 * math.pi) - math.pi
    theta *= sn
    nx = int(ra * math.sin(theta) + xo + 0.5)
    ny = int(ro - ra * math.cos(theta) + yo + 0.5)
    return nx, ny


def base_datetime(now: datetime) -> tuple[str, str]:
    """지금 조회할 수 있는 가장 최근 발표 시각 (base_date, base_time)."""
    t = now.astimezone(KST) - timedelta(minutes=15)
    hours = [h for h in BASE_HOURS if h <= t.hour]
    if hours:
        return t.strftime("%Y%m%d"), f"{hours[-1]:02d}00"
    return (t - timedelta(days=1)).strftime("%Y%m%d"), "2300"


def _pcp_mm(text: str) -> float:
    """PCP(1시간 강수량) 문자열 → mm. 예: '강수없음', '1mm 미만', '2.0mm', '30.0~50.0mm', '50.0mm 이상'."""
    if not text or "없음" in text:
        return 0.0
    if "미만" in text:
        return 0.5
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]
    return max(nums) if nums else 0.0


def to_wmo(sky: str | None, pty: str | None, pcp_mm: float = 0.0) -> int:
    """하늘상태(SKY)·강수형태(PTY) → weather.WMO 코드."""
    p = int(pty or 0)
    if p in (1, 5):  # 비, 빗방울
        return 65 if pcp_mm >= 15 else 63 if pcp_mm >= 3 else 61
    if p in (2, 6):  # 비/눈, 빗방울눈날림
        return 68
    if p in (3, 7):  # 눈, 눈날림
        return 73 if pcp_mm >= 3 else 71
    if p == 4:  # 소나기
        return 80
    return {1: 0, 3: 2, 4: 3}.get(int(sky or 1), 2)


def to_open_meteo(items: list[dict], now: datetime) -> dict:
    # (날짜, 시각) 별로 항목 모으기
    slots: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    tmn: dict[str, float] = {}
    tmx: dict[str, float] = {}
    for it in items:
        key = (it["fcstDate"], it["fcstTime"])
        cat, val = it["category"], it["fcstValue"]
        slots[key][cat] = val
        if cat == "TMN":
            tmn[it["fcstDate"]] = float(val)
        elif cat == "TMX":
            tmx[it["fcstDate"]] = float(val)

    hourly = {"time": [], "temperature_2m": [], "precipitation_probability": [], "weather_code": []}
    per_day: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    rows = []
    for (d, t) in sorted(slots):
        v = slots[(d, t)]
        if "TMP" not in v:
            continue
        pcp = _pcp_mm(v.get("PCP", ""))
        code = to_wmo(v.get("SKY"), v.get("PTY"), pcp)
        temp = float(v["TMP"])
        pop = float(v.get("POP", 0))
        iso = f"{d[:4]}-{d[4:6]}-{d[6:]}T{t[:2]}:00"
        hourly["time"].append(iso)
        hourly["temperature_2m"].append(temp)
        hourly["precipitation_probability"].append(pop)
        hourly["weather_code"].append(code)
        day = iso[:10]
        pd = per_day[day]
        pd["temp"].append(temp)
        pd["pop"].append(pop)
        pd["rain"].append(pcp)
        if 6 <= int(t[:2]) <= 21:
            pd["code"].append(code)
        rows.append((iso, temp, code, v))

    if not rows:
        raise ValueError("기상청 응답에 시간별 기온(TMP)이 없습니다")

    days = sorted(per_day)[:2]
    daily = {
        "weather_code": [max(per_day[d]["code"] or [0]) for d in days],
        "temperature_2m_max": [tmx.get(d.replace("-", ""), max(per_day[d]["temp"])) for d in days],
        "temperature_2m_min": [tmn.get(d.replace("-", ""), min(per_day[d]["temp"])) for d in days],
        "precipitation_probability_max": [max(per_day[d]["pop"] or [0]) for d in days],
        "precipitation_sum": [round(sum(per_day[d]["rain"]), 1) for d in days],
        "uv_index_max": [None for _ in days],
    }

    # 현재 날씨: 지금 시각과 가장 가까운 예보 시간
    now_iso = now.astimezone(KST).strftime("%Y-%m-%dT%H:00")
    cur = next((r for r in rows if r[0] >= now_iso), rows[0])
    _, temp, code, v = cur
    wind = float(v.get("WSD", 0))
    current = {
        "temperature_2m": temp,
        "apparent_temperature": _feels_like(temp, wind),
        "relative_humidity_2m": int(float(v.get("REH", 0))),
        "weather_code": code,
        "wind_speed_10m": wind,
    }
    # analyze() 는 hourly 첫 시각의 날짜를 '오늘'로 본다 → 지금 이후 시각부터 남긴다
    start = next((i for i, t in enumerate(hourly["time"]) if t[:10] == now_iso[:10]), 0)
    hourly = {k: vals[start:] for k, vals in hourly.items()}
    return {"current": current, "hourly": hourly, "daily": daily}


def fetch_forecast(lat: float, lon: float, now: datetime | None = None) -> dict:
    key = api_key()
    if not key:
        raise RuntimeError("KMA_API_KEY 가 설정되지 않았습니다")
    now = now or datetime.now(KST)
    nx, ny = latlon_to_grid(lat, lon)
    base_date, base_time = base_datetime(now)
    try:
        resp = requests.get(
            URL,
            params={
                "serviceKey": key, "pageNo": 1, "numOfRows": 1000, "dataType": "JSON",
                "base_date": base_date, "base_time": base_time, "nx": nx, "ny": ny,
            },
            timeout=20,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        # 오류 메시지에 인증키가 담긴 URL 이 들어가므로 키를 지우고 다시 던진다
        raise RuntimeError(f"기상청 API 요청 실패: {type(exc).__name__}: {str(exc).replace(key, '***')}") from None
    text = resp.text.strip()
    if text.startswith("<"):  # 인증키 오류 등은 JSON 요청에도 XML 로 온다
        raise RuntimeError(f"기상청 API 오류: {text[:300].replace(key, '***')}")
    body = resp.json()["response"]
    if body["header"]["resultCode"] != "00":
        raise RuntimeError(f"기상청 API 오류: {body['header']}")
    items = body["body"]["items"]["item"]
    return to_open_meteo(items, now)
