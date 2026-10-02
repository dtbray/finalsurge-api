from __future__ import annotations

import subprocess
import threading
import time as clock
from dataclasses import dataclass
from datetime import date, time
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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


@dataclass(frozen=True)
class LibraryWorkout:
    key: str
    name: str
    description: str
    activity_type: str
    distance_miles: float | None
    duration_minutes: int | None


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
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0
        self.session = requests.Session()
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update(
            {
                "User-Agent": "finalsurge-api/0.1 (personal automation)",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    @classmethod
    def from_1password(
        cls, *, vault: str = "Homelab", item: str = "log.finalsurge.com"
    ) -> FinalSurgeClient:
        """Load Final Surge credentials into memory from the 1Password CLI."""
        return cls(
            cls._onepassword_field(item, vault, "username"),
            cls._onepassword_field(item, vault, "password"),
        )

    def login(self) -> None:
        login_page = self._request("GET", "login.cshtml", allow_redirects=False)
        soup = BeautifulSoup(login_page.text, "html.parser")
        form = next(
            (
                candidate
                for candidate in soup.select("form")
                if candidate.select_one('[name="login_name"]')
            ),
            None,
        )
        if form is None:
            raise AuthenticationError("Final Surge login form was not found.")
        credentials = {
            "SubmitType": "Login",
            "login_name": self.username,
            "login_password": self.password,
            "login_remember": "on",
            "page_redirect": "/",
        }
        # Preserve repeated hidden controls, not unchecked or non-data inputs.
        payload = [
            (str(field["name"]), str(field.get("value", "")))
            for field in form.select('input[type="hidden"][name]')
            if not field.has_attr("disabled")
            and field.find_parent("fieldset", disabled=True) is None
            and field["name"] not in credentials
        ]
        payload.extend(credentials.items())
        destination = urljoin(login_page.url, form.get("action") or login_page.url)
        if not self._same_origin(destination):
            raise AuthenticationError("Final Surge login action must be same-origin.")
        response = self._request(
            "POST", destination, data=payload, allow_redirects=False
        )
        for _ in range(5):
            if not 300 <= response.status_code < 400:
                break
            location = response.headers.get("Location", "").strip()
            if not location:
                raise AuthenticationError("Final Surge login redirect has no Location.")
            redirect = urljoin(response.url, location)
            if not self._same_origin(redirect):
                raise AuthenticationError(
                    "Final Surge login redirect must be same-origin."
                )
            response = self._request("GET", redirect, allow_redirects=False)
        self._require_authenticated(response)
        if (
            300 <= response.status_code < 400
            or not self._same_origin(response.url)
            or urlsplit(response.url).path not in {"", "/"}
            or "Dashboard" not in response.text
        ):
            raise AuthenticationError(
                "Final Surge login failed or needs interactive MFA."
            )

    @staticmethod
    def _same_origin(url: str) -> bool:
        try:
            parsed = urlsplit(url)
            port = parsed.port if parsed.port is not None else 443
            return (
                parsed.scheme.lower() == "https"
                and parsed.hostname == urlsplit(BASE_URL).hostname
                and port == 443
                and parsed.username is None
                and parsed.password is None
            )
        except ValueError:
            return False

    def calendar(self, day: date) -> str:
        response = self._request(
            "GET",
            "Calendar.cshtml",
            params={"m": day.month, "d": day.day, "y": day.year},
        )
        self._require_authenticated(response)
        return response.text

    def list_library(self) -> list[LibraryWorkout]:
        response = self._request("GET", "WorkoutLibrary.cshtml")
        self._require_authenticated(response)
        return self._parse_library(response.text)

    def schedule_library_workout(
        self,
        library_workout: LibraryWorkout,
        day: date,
        *,
        allow_writes: bool = False,
    ) -> requests.Response:
        """Schedule a library entry without modifying the source library item."""
        return self.create_planned_workout(
            PlannedWorkout(
                day=day,
                name=library_workout.name,
                description=library_workout.description,
                distance_miles=library_workout.distance_miles,
                duration_minutes=library_workout.duration_minutes,
                activity_type=library_workout.activity_type,
            ),
            allow_writes=allow_writes,
        )

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
        date_text = self._format_date(workout.day)
        time_text = workout.at.strftime("%I:%M %p").lstrip("0") if workout.at else ""
        distance = "" if workout.distance_miles is None else str(workout.distance_miles)
        duration = self._format_duration(workout.duration_minutes)
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
        with self._request_lock:
            wait = self.min_request_interval - (
                clock.monotonic() - self._last_request_at
            )
            if wait > 0:
                clock.sleep(wait)
            self._last_request_at = clock.monotonic()
        kwargs.setdefault("timeout", self.timeout)
        response = self.session.request(method, urljoin(BASE_URL, path), **kwargs)
        response.raise_for_status()
        return response

    @staticmethod
    def _format_duration(minutes: int | None) -> str:
        """Format planned minutes as Final Surge's ``H:MM:SS`` form value."""
        if minutes is None:
            return ""
        hours, remaining_minutes = divmod(minutes, 60)
        return f"{hours}:{remaining_minutes:02d}:00"

    @staticmethod
    def _format_date(value: date | None) -> str:
        return "" if value is None else f"{value.month}/{value.day}/{value.year}"

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

    @staticmethod
    def _onepassword_field(item: str, vault: str, field: str) -> str:
        try:
            return subprocess.run(
                [
                    "op",
                    "item",
                    "get",
                    item,
                    "--vault",
                    vault,
                    "--fields",
                    field,
                    "--reveal",
                ],
                check=True,
                capture_output=True,
                encoding="utf-8",
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise AuthenticationError(
                "Could not load Final Surge credentials from 1Password."
            ) from exc

    @staticmethod
    def _parse_library(html: str) -> list[LibraryWorkout]:
        workouts: list[LibraryWorkout] = []
        for row in BeautifulSoup(html, "html.parser").select("tr"):
            link = row.select_one('a[href*="WorkoutLibrary.cshtml?key="]')
            cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
            if link is None or len(cells) < 2:
                continue
            key = link["href"].split("key=", 1)[1].split("&", 1)[0]
            subtype, name, *remaining = cells
            distance = next((value for value in remaining if value.endswith(" mi")), "")
            duration = next((value for value in remaining if ":" in value), "")
            description = next(
                (value for value in remaining if value not in {distance, duration}), ""
            )
            workouts.append(
                LibraryWorkout(
                    key=key,
                    name=name or subtype,
                    description=description,
                    activity_type=RUN_ACTIVITY if "Run" in subtype else "",
                    distance_miles=(
                        float(distance.removesuffix(" mi")) if distance else None
                    ),
                    duration_minutes=FinalSurgeClient._duration_minutes(duration),
                )
            )
        return workouts

    @staticmethod
    def _duration_minutes(value: str) -> int | None:
        if not value:
            return None
        parts = value.split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            if len(parts) == 3:
                return int(parts[0]) * 60 + int(parts[1]) + round(int(parts[2]) / 60)
        except ValueError:
            return None
        return None
