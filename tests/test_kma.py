"""기상청 단기예보 변환·격자 계산·우선순위 동작 테스트."""

from datetime import date, datetime, timedelta, timezone

import requests

from briefing_bot import kma, weather

KST = timezone(timedelta(hours=9))


def test_latlon_to_grid_known_points():
    assert kma.latlon_to_grid(37.5665, 126.9780) == (60, 127)  # 서울시청
    assert kma.latlon_to_grid(35.1796, 129.0756) == (98, 76)  # 부산시청
    nx, ny = kma.latlon_to_grid(37.1830, 127.1130)  # 동탄9동
    assert 60 <= nx <= 64 and 117 <= ny <= 121


def test_base_datetime():
    assert kma.base_datetime(datetime(2026, 11, 18, 6, 25, tzinfo=KST)) == ("20261118", "0500")
    assert kma.base_datetime(datetime(2026, 11, 18, 5, 10, tzinfo=KST)) == ("20261118", "0200")
    assert kma.base_datetime(datetime(2026, 11, 18, 1, 0, tzinfo=KST)) == ("20261117", "2300")
    assert kma.base_datetime(datetime(2026, 11, 18, 16, 50, tzinfo=KST)) == ("20261118", "1400")


def test_pcp_and_wmo():
    assert kma._pcp_mm("강수없음") == 0 and kma._pcp_mm("1mm 미만") == 0.5
    assert kma._pcp_mm("30.0~50.0mm") == 50 and kma._pcp_mm("50.0mm 이상") == 50
    assert kma.to_wmo("1", "0") == 0 and kma.to_wmo("3", "0") == 2 and kma.to_wmo("4", "0") == 3
    assert kma.to_wmo("4", "1", 0.5) == 61 and kma.to_wmo("4", "1", 20) == 65
    assert kma.to_wmo("4", "3", 1) == 71 and kma.to_wmo("4", "4") == 80 and kma.to_wmo("4", "2") == 68


def _items():
    """2026-11-18 05시 발표: 06시~ 이틀치. 낮(12~15시)에 비."""
    out = []
    start = datetime(2026, 11, 18, 6, tzinfo=KST)
    for h in range(42):
        t = start + timedelta(hours=h)
        d, hh = t.strftime("%Y%m%d"), t.strftime("%H%M")
        rainy = t.day == 18 and 12 <= t.hour <= 15
        vals = {
            "TMP": str(3 + (h % 24) // 2), "POP": "80" if rainy else "10",
            "PTY": "1" if rainy else "0", "SKY": "4" if rainy else "3",
            "PCP": "2.0mm" if rainy else "강수없음", "REH": "75", "WSD": "2.5",
        }
        for cat, v in vals.items():
            out.append({"fcstDate": d, "fcstTime": hh, "category": cat, "fcstValue": v})
    out += [
        {"fcstDate": "20261118", "fcstTime": "0600", "category": "TMN", "fcstValue": "1.0"},
        {"fcstDate": "20261118", "fcstTime": "1500", "category": "TMX", "fcstValue": "12.0"},
        {"fcstDate": "20261119", "fcstTime": "0600", "category": "TMN", "fcstValue": "-2.0"},
        {"fcstDate": "20261119", "fcstTime": "1500", "category": "TMX", "fcstValue": "9.0"},
    ]
    return out


def test_kma_converts_and_renders():
    now = datetime(2026, 11, 18, 7, 5, tzinfo=KST)
    fc = kma.to_open_meteo(_items(), now)
    assert fc["daily"]["temperature_2m_min"] == [1.0, -2.0]
    assert fc["daily"]["temperature_2m_max"] == [12.0, 9.0]
    assert fc["daily"]["precipitation_probability_max"][0] == 80
    assert fc["daily"]["weather_code"][0] == 61
    assert fc["current"]["temperature_2m"] == 3.0  # 07시 예보
    assert fc["hourly"]["time"][0] == "2026-11-18T06:00"

    r = weather.analyze(weather.Location("동탄9동", 37.18, 127.11), {"forecast": fc, "air": None})
    assert r["tmin"] == 1 and r["tmax"] == 12 and r["slots"]["낮"]["rain"] == 80
    assert "우산" in " ".join(r["tips"]) and r["tomorrow"]["tmin"] == -2
    md = weather.render_markdown(date(2026, 11, 18), [r])
    assert "🌧️ 약한 비" in md and "최저 1°C / 최고 12°C" in md
    assert "강수확률 80%" in md and ".0%" not in md


def test_kma_is_primary_and_falls_back(monkeypatch):
    monkeypatch.setenv("KMA_API_KEY", "SECRETKEY123")
    used = []

    def fake_kma(lat, lon):
        used.append("kma")
        return kma.to_open_meteo(_items(), datetime(2026, 11, 18, 7, 5, tzinfo=KST))

    monkeypatch.setattr(kma, "fetch_forecast", fake_kma)
    monkeypatch.setattr(weather, "_get_json", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("x")))
    data = weather.fetch(weather.Location("동탄9동", 37.18, 127.11))
    assert used == ["kma"] and data["forecast"]["daily"]["temperature_2m_min"][0] == 1.0

    # 기상청이 실패하면 Open-Meteo/MET 경로로 넘어간다
    def broken(lat, lon):
        raise RuntimeError("기상청 API 오류")

    monkeypatch.setattr(kma, "fetch_forecast", broken)
    monkeypatch.setattr(weather, "_fetch_open_meteo_or_metno", lambda loc, common: {"from": "fallback"})
    data = weather.fetch(weather.Location("동탄9동", 37.18, 127.11))
    assert data["forecast"] == {"from": "fallback"}


def test_kma_error_hides_key(monkeypatch):
    monkeypatch.setenv("KMA_API_KEY", "SECRETKEY123")

    def fake_get(url, params=None, timeout=None):
        raise requests.ConnectionError(f"failed for {url}?serviceKey={params['serviceKey']}")

    monkeypatch.setattr(kma.requests, "get", fake_get)
    try:
        kma.fetch_forecast(37.18, 127.11)
    except RuntimeError as exc:
        assert "SECRETKEY123" not in str(exc) and "***" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
