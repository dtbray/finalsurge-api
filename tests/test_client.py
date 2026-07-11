from datetime import date, time

import pytest

from finalsurge_api import FinalSurgeClient, PlannedWorkout, WriteProtectionError


def test_calendar_payload_matches_discovered_quick_add_contract():
    client = FinalSurgeClient("user", "password")
    payload = client._calendar_payload(
        PlannedWorkout(
            date(2026, 10, 1),
            "Easy run",
            description="Keep it comfortable.",
            distance_miles=5,
            duration_minutes=50,
            at=time(6, 0),
        )
    )

    assert payload["Add"] == "1"
    assert payload["Edit"] == "0"
    assert payload["WorkoutDate"] == "10/1/2026"
    assert payload["WorkoutTime"] == "6:00 AM"
    assert payload["PlannedWorkout"] == "True"
    assert payload["PDistance"] == "5"
    assert payload["PDuration"] == "50"
    assert payload["btnSubmit"] == "Add Workout"


def test_write_requires_explicit_opt_in():
    client = FinalSurgeClient("user", "password")
    workout = PlannedWorkout(date(2026, 10, 1), "Easy run")

    with pytest.raises(WriteProtectionError):
        client.create_planned_workout(workout)
