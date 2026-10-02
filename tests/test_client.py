from datetime import date, time

import pytest

from finalsurge_api import (
    FinalSurgeClient,
    LibraryWorkout,
    PlannedWorkout,
    WriteProtectionError,
)


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
    assert payload["PDuration"] == "0:50:00"
    assert payload["btnSubmit"] == "Add Workout"


def test_write_requires_explicit_opt_in():
    client = FinalSurgeClient("user", "password")
    workout = PlannedWorkout(date(2026, 10, 1), "Easy run")

    with pytest.raises(WriteProtectionError):
        client.create_planned_workout(workout)


def test_duration_serializes_hours_and_minutes_for_finalsurge():
    client = FinalSurgeClient("user", "password")
    payload = client._calendar_payload(
        PlannedWorkout(date(2026, 10, 1), "Long run", duration_minutes=90)
    )

    assert payload["PDuration"] == "1:30:00"


def test_parse_library_preserves_planned_distance_and_duration():
    workouts = FinalSurgeClient._parse_library(
        """
        <table><tr>
          <td>Long Run</td><td>Run 10</td><td>Comfortable effort</td>
          <td>10 mi</td><td>1:30:00</td>
          <td><a href="WorkoutLibrary.cshtml?key=abc&folderid=def">open</a></td>
        </tr></table>
        """
    )

    assert workouts == [
        LibraryWorkout(
            key="abc",
            name="Run 10",
            description="Comfortable effort",
            activity_type="00000001-0001-0001-0001-000000000001",
            distance_miles=10,
            duration_minutes=90,
        )
    ]
