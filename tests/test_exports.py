import finalsurge_api


def test_public_exports_compose_gear_and_strava_clients():
    expected = {
        "Bike",
        "Shoe",
        "FinalSurgeClient",
        "GearReport",
        "StravaActivity",
        "StravaAuthenticationError",
        "StravaClient",
        "StravaError",
        "StravaGear",
    }
    assert expected <= set(finalsurge_api.__all__)
    for name in finalsurge_api.__all__:
        assert getattr(finalsurge_api, name) is not None
