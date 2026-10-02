from datetime import date

import responses

from finalsurge_api import StravaClient


@responses.activate
def test_gear_report_combines_lifetime_and_window_mileage(tmp_path):
    client = StravaClient("token", min_request_interval=0)
    base = "https://www.strava.com/api/v3/"
    responses.add(
        responses.GET,
        f"{base}athlete/activities",
        json=[
            {
                "id": 11,
                "name": "Easy run",
                "sport_type": "Run",
                "start_date": "2026-07-01T12:00:00Z",
                "distance": 8046.72,
                "gear_id": "g1",
            },
            {
                "id": 12,
                "name": "No shoe run",
                "sport_type": "Run",
                "start_date": "2026-07-02T12:00:00Z",
                "distance": 1609.344,
                "gear_id": None,
            },
        ],
    )
    responses.add(responses.GET, f"{base}athlete/activities", json=[])
    responses.add(
        responses.GET,
        f"{base}athlete",
        json={"shoes": [{"id": "g1", "name": "Daily trainer", "distance": 80467.2}]},
    )
    responses.add(
        responses.GET,
        f"{base}gear/g1",
        json={
            "id": "g1",
            "name": "Daily trainer",
            "brand_name": "Example",
            "model_name": "Fast",
            "distance": 160934.4,
            "primary": True,
        },
    )

    reports = client.gear_report(after=date(2026, 7, 1))

    assert len(reports) == 1
    # Detail mileage wins over the intentionally different athlete summary.
    assert reports[0].gear.lifetime_miles == 100
    assert reports[0].gear.brand_name == "Example"
    assert sum(call.request.url == f"{base}gear/g1" for call in responses.calls) == 1
    assert reports[0].period_miles == 5
    assert reports[0].activity_count == 1

    output = tmp_path / "gear.csv"
    client.export_gear_report_csv(reports, output)
    assert output.read_text() == (
        "gear_id,name,brand,model,is_primary,lifetime_miles,period_miles,activity_count\n"
        "g1,Daily trainer,Example,Fast,True,100.00,5.00,1\n"
    )


@responses.activate
def test_gear_report_keeps_mileage_for_retired_or_unknown_shoes():
    client = StravaClient("token", min_request_interval=0)
    base = "https://www.strava.com/api/v3/"
    responses.add(
        responses.GET,
        f"{base}athlete/activities",
        json=[
            {
                "id": 99,
                "name": "Old shoe run",
                "type": "Run",
                "start_date": "2026-07-01T12:00:00Z",
                "distance": 1609.344,
                "gear_id": "retired",
            }
        ],
    )
    responses.add(responses.GET, f"{base}athlete", json={"shoes": []})

    reports = client.gear_report()

    assert reports[0].gear.name == "Unknown or retired shoe"
    assert reports[0].period_miles == 1
    assert reports[0].activity_count == 1
