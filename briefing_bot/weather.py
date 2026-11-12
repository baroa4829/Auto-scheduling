"""Open-Meteo(무료, API 키 불필요)로 오늘 날씨 + 미세먼지 브리핑을 만든다."""

from __future__ import annotations

import html
import logging
import os
from dataclasses import dataclass
from datetime import date

import requests

log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# WMO weather code → (이모지, 설명)
WMO: dict[int, tuple[str, str]] = {
    0: ("☀️", "맑음"),
    1: ("🌤️", "대체로 맑음"),
    2: ("⛅", "구름 조금"),
    3: ("☁️", "흐림"),
    45: ("🌫️", "안개"),
    48: ("🌫️", "짙은 안개"),
    51: ("🌦️", "약한 이슬비"),
    53: ("🌦️", "이슬비"),
    55: ("🌧️", "강한 이슬비"),
    56: ("🌧️", "어는 이슬비"),
    57: ("🌧️", "어는 이슬비"),
    61: ("🌧️", "약한 비"),
    63: ("🌧️", "비"),
    65: ("🌧️", "강한 비"),
    66: ("🌧️", "어는 비"),
    67: ("🌧️", "어는 비"),
    71: ("🌨️", "약한 눈"),
    73: ("🌨️", "눈"),
    75: ("❄️", "많은 눈"),
    77: ("🌨️", "싸락눈"),
    80: ("🌦️", "소나기"),
    81: ("🌧️", "강한 소나기"),
    82: ("⛈️", "매우 강한 소나기"),
    85: ("🌨️", "눈 소나기"),
    86: ("❄️", "강한 눈 소나기"),
    95: ("⛈️", "뇌우"),
    96: ("⛈️", "우박 동반 뇌우"),
    99: ("⛈️", "강한 우박 뇌우"),
}

# 기본 지역: 경기 화성시 동탄9동 (신동 일대)
DEFAULT_LOCATIONS = "화성 동탄9동:37.1830:127.1130"


@dataclass
class Location:
    name: str
    lat: float
    lon: float


def parse_locations(spec: str | None = None) -> list[Location]:
    """'서울:37.56:126.97,부산:35.18:129.07' 형식."""
    spec = spec or os.environ.get("WEATHER_LOCATIONS") or DEFAULT_LOCATIONS
    out = []
    for item in spec.split(","):
        name, lat, lon = item.strip().split(":")
        out.append(Location(name.strip(), float(lat), float(lon)))
    return out


def _wmo(code: int | None) -> tuple[str, str]:
    return WMO.get(int(code or 0), ("🌡️", "알 수 없음"))


def _grade(value: float | None, bounds: tuple[float, float, float]) -> str:
    """환경부 기준 등급: 좋음/보통/나쁨/매우나쁨."""
    if value is None:
        return "정보 없음"
    good, normal, bad = bounds
    if value <= good:
        return "좋음"
    if value <= normal:
        return "보통"
    if value <= bad:
        return "나쁨"
    return "매우나쁨"


PM10_BOUNDS = (30, 80, 150)
PM25_BOUNDS = (15, 35, 75)


def fetch(loc: Location) -> dict:
    common = {"latitude": loc.lat, "longitude": loc.lon, "timezone": "Asia/Seoul"}
    fc = requests.get(
        FORECAST_URL,
        params={
            **common,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,precipitation_sum,uv_index_max",
            "wind_speed_unit": "ms",
            "forecast_days": 1,
        },
        timeout=15,
    )
    fc.raise_for_status()
    data = {"forecast": fc.json(), "air": None}
    try:
        air = requests.get(
            AIR_URL, params={**common, "current": "pm10,pm2_5"}, timeout=15
        )
        air.raise_for_status()
        data["air"] = air.json()
    except requests.RequestException as exc:
        log.warning("미세먼지 정보 조회 실패 (%s): %s", loc.name, exc)
    return data


def analyze(loc: Location, data: dict) -> dict:
    """API 응답을 브리핑용 값으로 정리한다."""
    fc = data["forecast"]
    cur, daily, hourly = fc["current"], fc["daily"], fc.get("hourly", {})

    tmax, tmin = daily["temperature_2m_max"][0], daily["temperature_2m_min"][0]
    rain_prob = daily.get("precipitation_probability_max", [0])[0] or 0
    rain_sum = daily.get("precipitation_sum", [0])[0] or 0
    uv = daily.get("uv_index_max", [None])[0]

    # 시간대별 요약: 아침(6~9) / 낮(12~15) / 저녁(18~21)
    slots = {}
    times = hourly.get("time", [])
    for label, hours in (("아침", range(6, 10)), ("낮", range(12, 16)), ("저녁", range(18, 22))):
        idx = [i for i, t in enumerate(times) if int(t[11:13]) in hours]
        if not idx:
            continue
        temps = [hourly["temperature_2m"][i] for i in idx]
        probs = [hourly["precipitation_probability"][i] or 0 for i in idx]
        codes = [hourly["weather_code"][i] for i in idx]
        slots[label] = {
            "temp": round(sum(temps) / len(temps)),
            "rain": max(probs),
            "code": max(codes),  # 가장 나쁜 날씨 기준
        }

    pm10 = pm25 = None
    if data.get("air"):
        ac = data["air"].get("current", {})
        pm10, pm25 = ac.get("pm10"), ac.get("pm2_5")

    pm10_g, pm25_g = _grade(pm10, PM10_BOUNDS), _grade(pm25, PM25_BOUNDS)

    tips = []
    if rain_prob >= 50 or rain_sum >= 1:
        tips.append("☂️ 우산 챙기세요")
    elif rain_prob >= 30:
        tips.append("🌂 접이식 우산이 있으면 좋아요")
    if tmax - tmin >= 10:
        tips.append(f"🧥 일교차가 {round(tmax - tmin)}도로 커요. 겉옷을 챙기세요")
    if tmin <= -5:
        tips.append("🧤 한파 수준 추위, 방한용품 필수")
    elif tmax >= 33:
        tips.append("🥵 폭염 수준, 수분 보충하세요")
    if "나쁨" in (pm10_g, pm25_g) or "매우나쁨" in (pm10_g, pm25_g):
        tips.append("😷 미세먼지가 나빠요. 마스크를 착용하세요")
    if uv is not None and uv >= 8:
        tips.append("🧴 자외선이 매우 강해요")

    return {
        "name": loc.name,
        "now_temp": round(cur["temperature_2m"]),
        "feels": round(cur["apparent_temperature"]),
        "humidity": cur.get("relative_humidity_2m"),
        "wind": cur.get("wind_speed_10m"),
        "now_code": cur["weather_code"],
        "day_code": daily["weather_code"][0],
        "tmax": round(tmax),
        "tmin": round(tmin),
        "rain_prob": rain_prob,
        "rain_sum": rain_sum,
        "uv": uv,
        "slots": slots,
        "pm10": pm10,
        "pm25": pm25,
        "pm10_grade": pm10_g,
        "pm25_grade": pm25_g,
        "tips": tips,
    }


def render_markdown(day: date, reports: list[dict], weekdays: str = "월화수목금토일") -> str:
    lines = [f"# 🌤️ 오늘의 날씨 — {day:%Y.%m.%d}({weekdays[day.weekday()]})", ""]
    for r in reports:
        emoji, desc = _wmo(r["day_code"])
        now_emoji, now_desc = _wmo(r["now_code"])
        lines += [
            f"## {r['name']} {emoji} {desc}",
            f"- 현재 {now_emoji} {now_desc} {r['now_temp']}°C (체감 {r['feels']}°C), "
            f"습도 {r['humidity']}%, 바람 {r['wind']}m/s",
            f"- 최저 {r['tmin']}°C / 최고 {r['tmax']}°C, 강수확률 {r['rain_prob']}%",
        ]
        if r["slots"]:
            slot_txt = " · ".join(
                f"{k} {_wmo(v['code'])[0]} {v['temp']}°C({v['rain']}%)" for k, v in r["slots"].items()
            )
            lines.append(f"- {slot_txt}")
        if r["pm10"] is not None:
            lines.append(
                f"- 미세먼지 {r['pm10_grade']}({round(r['pm10'])}㎍/㎥) · "
                f"초미세먼지 {r['pm25_grade']}({round(r['pm25'])}㎍/㎥)"
            )
        if r["tips"]:
            lines.append("")
            lines += [f"> {t}" for t in r["tips"]]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_telegram(day: date, reports: list[dict], weekdays: str = "월화수목금토일") -> list[str]:
    msgs = []
    for r in reports:
        emoji, desc = _wmo(r["day_code"])
        now_emoji, now_desc = _wmo(r["now_code"])
        buf = [
            f"🌤️ <b>오늘의 날씨 · {html.escape(r['name'])}</b>  {day:%m/%d}({weekdays[day.weekday()]})",
            "",
            f"{emoji} <b>{desc}</b>  최저 {r['tmin']}° / 최고 {r['tmax']}°",
            f"지금 {now_emoji} {now_desc} {r['now_temp']}° (체감 {r['feels']}°)",
            f"강수확률 {r['rain_prob']}% · 습도 {r['humidity']}% · 바람 {r['wind']}m/s",
        ]
        if r["slots"]:
            buf.append("")
            for k, v in r["slots"].items():
                buf.append(f"{k}  {_wmo(v['code'])[0]} {v['temp']}°  ☔{v['rain']}%")
        if r["pm10"] is not None:
            buf.append("")
            buf.append(
                f"미세먼지 {r['pm10_grade']} · 초미세먼지 {r['pm25_grade']}"
            )
        if r["tips"]:
            buf.append("")
            buf += [html.escape(t) for t in r["tips"]]
        msgs.append("\n".join(buf))
    return msgs


def build(day: date) -> tuple[str, list[str]]:
    """(마크다운, 텔레그램 메시지 목록) 반환."""
    reports = []
    for loc in parse_locations():
        try:
            reports.append(analyze(loc, fetch(loc)))
        except (requests.RequestException, KeyError, IndexError, TypeError) as exc:
            log.error("날씨 조회 실패 (%s): %s", loc.name, exc)
    if not reports:
        raise RuntimeError("날씨 정보를 가져오지 못했습니다")
    return render_markdown(day, reports), render_telegram(day, reports)
