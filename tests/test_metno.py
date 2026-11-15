"""예비 날씨 소스(MET Norway) 변환과 Open-Meteo 429 대체 동작 테스트."""

from datetime import date

import requests

from briefing_bot import weather


# ---------------- 예비 날씨 소스 (MET Norway) ----------------

def _metno_fixture():
    """2026-11-15 22:00Z(= 11/16 07:00 KST) 부터 48시간 + 6시간 단위 꼬리."""
    from datetime import datetime as dt, timedelta as td, timezone as tz
    start = dt(2026, 11, 15, 22, tzinfo=tz.utc)
    series = []
    for h in range(48):
        t = start + td(hours=h)
        kst_hour = (t.hour + 9) % 24
        rainy = 12 <= kst_hour <= 15 and h < 24  # 첫날 낮에 비
        series.append({
            "time": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data": {
                "instant": {"details": {
                    "air_temperature": 2.0 + (h % 24) * 0.5,
                    "relative_humidity": 80.0, "wind_speed": 3.0,
                    "ultraviolet_index_clear_sky": 1.5,
                }},
                "next_1_hours": {
                    "summary": {"symbol_code": "lightrain" if rainy else "partlycloudy_day"},
                    "details": {"precipitation_amount": 0.8 if rainy else 0.0,
                                "probability_of_precipitation": 70.0 if rainy else 5.0},
                },
            },
        })
    series.append({"time": "2026-11-17T22:00:00Z", "data": {
        "instant": {"details": {"air_temperature": 1.0, "wind_speed": 2.0, "relative_humidity": 70}},
        "next_6_hours": {"summary": {"symbol_code": "cloudy"}, "details": {"precipitation_amount": 0}},
    }})
    return {"properties": {"timeseries": series}}


def test_metno_converts_to_open_meteo_shape():
    from briefing_bot import metno

    fc = metno.to_open_meteo(_metno_fixture())
    assert fc["hourly"]["time"][0] == "2026-11-16T07:00"
    assert fc["current"]["weather_code"] == 2 and fc["current"]["apparent_temperature"] < 2.0
    assert fc["daily"]["weather_code"][0] == 61  # 낮에 약한 비
    assert fc["daily"]["precipitation_probability_max"][0] == 70.0
    assert len(fc["daily"]["temperature_2m_max"]) == 2
    assert metno.symbol_to_wmo("heavyrainandthunder_night") == 95

    # analyze / render 가 그대로 동작해야 한다
    r = weather.analyze(weather.Location("동탄9동", 37.18, 127.11), {"forecast": fc, "air": None})
    assert set(r["slots"]) >= {"아침", "낮", "저녁"} and r["slots"]["낮"]["rain"] == 70.0
    assert "우산" in " ".join(r["tips"])
    assert r["tomorrow"] is not None
    md = weather.render_markdown(date(2026, 11, 16), [r])
    assert "🌧️ 약한 비" in md


def test_weather_falls_back_to_metno_on_429(monkeypatch):
    from briefing_bot import metno

    class R429:
        status_code = 429

        def raise_for_status(self):
            raise requests.HTTPError("429 Too Many Requests", response=self)

    calls = []

    def fake_get(url, params=None, timeout=None, headers=None):
        calls.append(url)
        if "met.no" in url:
            class Ok:
                def raise_for_status(self):
                    pass

                def json(self):
                    return _metno_fixture()
            return Ok()
        return R429()

    monkeypatch.setattr(weather.requests, "get", fake_get)
    monkeypatch.setattr(metno.requests, "get", fake_get)
    monkeypatch.setattr(weather.time, "sleep", lambda *_: None)
    data = weather.fetch(weather.Location("동탄9동", 37.18, 127.11))
    assert data["forecast"]["hourly"]["time"][0] == "2026-11-16T07:00"
    assert data["air"] is None
    # 429 는 재시도하지 않는다: Open-Meteo 예보 1번 + MET 1번 + 미세먼지 1번
    assert sum("open-meteo.com/v1/forecast" in c for c in calls) == 1
