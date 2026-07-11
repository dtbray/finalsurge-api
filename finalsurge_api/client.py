from __future__ import annotations

import time as clock
from dataclasses import dataclass
from datetime import date, time
from urllib.parse import urljoin

import requests

from .exceptions import (
    AuthenticationError,
    FinalSurgeError,
    WriteProtectionError,
)

BASE_URL = "https://log.finalsurge.com/"
RUN_ACTIVITY = "00000001-0001-0001-0001-000000000001"


@dataclass(frozen=True)
class PlannedWorkout:
    day: date
    name: str
    description: str = ""
    distance_miles: float | None = None
    duration_minutes: int | None = None
    at: time | None = None
    activity_type: str = RUN_ACTIVITY


class FinalSurgeClient:
    """Private Final Surge web client.

    This follows the web calendar's form contract, not an official API. Writes
    are disabled by default and require ``allow_writes=True`` per call.
    """

    def __init__(
        self,
        username: str,
        password: str,
        *,
        timeout: float = 20,
        min_request_interval: float = 0.5,
    ) -> None:
        self.username = username
        self.password = password
        self.timeout = timeout
        self.min_request_interval = min_request_interval
        self._last_request_at = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "finalsurge-api/0.1 (personal automation)",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def login(self) -> None:
        response = self._request(
            "POST",
            "login.cshtml",
            data={
                "SubmitType": "Login",
                "login_name": self.username,
                "login_password": self.password,
                "login_remember": "on",
                "page_redirect": "/",
            },
            allow_redirects=True,
        )
        if (
            response.url.rstrip("/") != BASE_URL.rstrip("/")
            or "Dashboard" not in response.text
        ):
            raise AuthenticationError(
                "Final Surge login failed or needs interactive MFA."
            )

    def calendar(self, day: date) -> str:
        response = self._request(
            "GET",
            "Calendar.cshtml",
            params={"m": day.month, "d": day.day, "y": day.year},
        )
        self._require_authenticated(response)
        return response.text

    def create_planned_workout(
        self, workout: PlannedWorkout, *, allow_writes: bool = False
    ) -> requests.Response:
        if not allow_writes:
            raise WriteProtectionError(
                "Writes are disabled. Pass allow_writes=True only after review."
            )
        self._require_planned_workout(workout)
        response = self._request(
            "POST",
            "Calendar.cshtml",
            data=self._calendar_payload(workout),
            allow_redirects=True,
        )
        self._require_authenticated(response)
        if response.status_code >= 400:
            raise FinalSurgeError(
                f"Workout creation failed: HTTP {response.status_code}"
            )
        return response

    def _calendar_payload(self, workout: PlannedWorkout) -> dict[str, str]:
        date_text = workout.day.strftime("%-m/%-d/%Y")
        time_text = workout.at.strftime("%I:%M %p").lstrip("0") if workout.at else ""
        distance = "" if workout.distance_miles is None else str(workout.distance_miles)
        duration = (
            "" if workout.duration_minutes is None else str(workout.duration_minutes)
        )
        return {
            "Add": "1",
            "ViewStart": date_text,
            "ViewEnd": date_text,
            "Edit": "0",
            "EditKey": "",
            "AddVitals": "0",
            "WorkoutLibraryKey": "",
            "WorkoutDate": date_text,
            "WorkoutTime": time_text,
            "ActivityType": workout.activity_type,
            "Name": workout.name,
            "Desc": workout.description,
            "PlannedWorkout": "True",
            "PDistance": distance,
            "PDistType": "mi",
            "PDuration": duration,
            "Distance": "",
            "DistType": "mi",
            "Duration": "",
            "Pace": "",
            "PaceType": "mi",
            "HowFeel": "",
            "PerEffort": "",
            "PostDesc": "",
            "OverallPlace": "",
            "AgeGroupPlace": "",
            "btnSubmit": "Add Workout",
            "ActivityTypeFilter": "",
            "VitalsDate": date_text,
            "Steps": "",
            "Calories": "",
            "Weight": "",
            "WeightType": "lb",
            "BodyFat": "",
            "RestHR": "",
            "HRVar": "",
            "WaterPercent": "",
            "MuscleMass": "",
            "MuscleMassType": "lb",
            "SleepHours": "",
            "AwakeTime": "",
            "SleepAmount": "",
            "SleepQuality": "",
            "Stress": "",
            "Systolic": "",
            "Diastolic": "",
            "HealthNotes": "",
        }

    def _request(self, method: str, path: str, **kwargs: object) -> requests.Response:
        wait = self.min_request_interval - (clock.monotonic() - self._last_request_at)
        if wait > 0:
            clock.sleep(wait)
        self._last_request_at = clock.monotonic()
        kwargs.setdefault("timeout", self.timeout)
        response = self.session.request(method, urljoin(BASE_URL, path), **kwargs)
        response.raise_for_status()
        return response

    @staticmethod
    def _require_planned_workout(workout: PlannedWorkout) -> None:
        if not workout.name.strip():
            raise ValueError("A workout name is required.")
        if workout.distance_miles is not None and workout.distance_miles <= 0:
            raise ValueError("distance_miles must be positive.")
        if workout.duration_minutes is not None and workout.duration_minutes <= 0:
            raise ValueError("duration_minutes must be positive.")

    @staticmethod
    def _require_authenticated(response: requests.Response) -> None:
        if "login.cshtml" in response.url or "login_name" in response.text:
            raise AuthenticationError("Final Surge session is missing or expired.")
