"""노르웨이 기상청(MET Norway) Locationforecast 를 Open-Meteo 응답 모양으로 바꿔 준다.

GitHub Actions 서버에서는 Open-Meteo 가 아침마다 429(요청 과다)로 거절해서,
그럴 때 대신 쓰는 예비 날씨 소스다. 무료, API 키 불필요 (User-Agent 필수).
https://api.met.no/weatherapi/locationforecast/2.0/documentation
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
# MET Norway 는 앱을 식별할 수 있는 User-Agent 를 요구한다 (기본 python-requests 는 차단됨)
USER_AGENT = "daily-weather-briefing-bot/1.0 (personal use)"
KST = timezone(timedelta(hours=9))

# MET symbol_code → WMO weather code (weather.WMO 표와 맞춤)
SYMBOL_TO_WMO = {
    "clearsky": 0,
    "fair": 1,
    "partlycloudy": 2,
    "cloudy": 3,
    "fog": 45,
    "lightrain": 61, "lightrainshowers": 80,
    "rain": 63, "rainshowers": 81,
    "heavyrain": 65, "heavyrainshowers": 82,
    "lightsleet": 66, "lightsleetshowers": 66,
    "sleet": 67, "sleetshowers": 67, "heavysleet": 67, "heavysleetshowers": 67,
    "lightsnow": 71, "lightsnowshowers": 85,
    "snow": 73, "snowshowers": 85,
    "heavysnow": 75, "heavysnowshowers": 86,
}


def symbol_to_wmo(symbol: str | None) -> int:
    if not symbol:
        return 0
    base = symbol.split("_")[0]  # "rainshowers_day" → "rainshowers"
    if "thunder" in base:
        return 95
    return SYMBOL_TO_WMO.get(base, 3)


def _feels_like(temp: float, wind_ms: float) -> float:
    """체감온도 (기상청 겨울철 체감온도 식). 10℃ 이하·바람 1.3m/s 이상일 때만 적용."""
    v = wind_ms * 3.6
    if temp > 10 or v < 4.8:
        return temp
    return 13.12 + 0.6215 * temp - 11.37 * v**0.16 + 0.3965 * temp * v**0.16


def _rain_prob(block: dict) -> float:
    d = block.get("details", {})
    if "probability_of_precipitation" in d:
        return d["probability_of_precipitation"]
    amount = d.get("precipitation_amount", 0) or 0  # 확률이 없으면 강수량으로 대략 추정
    return 70 if amount >= 0.5 else 40 if amount > 0 else 0


def to_open_meteo(raw: dict) -> dict:
    series = raw["properties"]["timeseries"]
    hourly = {"time": [], "temperature_2m": [], "precipitation_probability": [], "weather_code": []}
    per_day: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    for item in series:
        t = datetime.fromisoformat(item["time"].replace("Z", "+00:00")).astimezone(KST)
        data = item["data"]
        inst = data["instant"]["details"]
        nxt = data.get("next_1_hours") or data.get("next_6_hours") or {}
        code = symbol_to_wmo(nxt.get("summary", {}).get("symbol_code"))
        prob = _rain_prob(nxt) if nxt else 0
        day = t.strftime("%Y-%m-%d")
        if data.get("next_1_hours"):  # 시간 단위 예보가 있는 구간만 시간별 표에 넣는다
            hourly["time"].append(t.strftime("%Y-%m-%dT%H:00"))
            hourly["temperature_2m"].append(inst["air_temperature"])
            hourly["precipitation_probability"].append(prob)
            hourly["weather_code"].append(code)
        d = per_day[day]
        d["temp"].append(inst["air_temperature"])
        d["prob"].append(prob)
        d["rain"].append((nxt.get("details", {}) or {}).get("precipitation_amount", 0) or 0
                         if data.get("next_1_hours") else 0)
        if 6 <= t.hour <= 21:
            d["code"].append(code)
        if "ultraviolet_index_clear_sky" in inst:
            d["uv"].append(inst["ultraviolet_index_clear_sky"])

    days = sorted(per_day)[:2]
    daily = {
        "weather_code": [max(per_day[d]["code"] or [0]) for d in days],
        "temperature_2m_max": [max(per_day[d]["temp"]) for d in days],
        "temperature_2m_min": [min(per_day[d]["temp"]) for d in days],
        "precipitation_probability_max": [max(per_day[d]["prob"] or [0]) for d in days],
        "precipitation_sum": [round(sum(per_day[d]["rain"]), 1) for d in days],
        "uv_index_max": [max(per_day[d]["uv"]) if per_day[d]["uv"] else None for d in days],
    }

    first = series[0]["data"]
    inst = first["instant"]["details"]
    nxt = first.get("next_1_hours") or first.get("next_6_hours") or {}
    current = {
        "temperature_2m": inst["air_temperature"],
        "apparent_temperature": _feels_like(inst["air_temperature"], inst.get("wind_speed", 0)),
        "relative_humidity_2m": round(inst.get("relative_humidity", 0)),
        "weather_code": symbol_to_wmo(nxt.get("summary", {}).get("symbol_code")),
        "wind_speed_10m": inst.get("wind_speed", 0),
    }
    return {"current": current, "hourly": hourly, "daily": daily}


def fetch_forecast(lat: float, lon: float) -> dict:
    resp = requests.get(
        URL,
        params={"lat": round(lat, 4), "lon": round(lon, 4)},
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    return to_open_meteo(resp.json())
