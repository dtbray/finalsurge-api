import finalsurge_api


def test_recovered_login_keeps_merged_strava_exports():
    expected = {
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


def test_unverified_gear_writes_are_not_published():
    assert not hasattr(finalsurge_api.FinalSurgeClient, "create_shoe")
    assert not hasattr(finalsurge_api.FinalSurgeClient, "create_bike")
