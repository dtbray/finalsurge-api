from __future__ import annotations

import subprocess
import threading
import time as clock
from dataclasses import dataclass
from datetime import date, time
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup, Tag
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
        self._authenticated = False
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
        previously_authenticated = self._authenticated
        self._authenticated = False
        login_page = self._follow_login_redirects(
            self._request("GET", "login.cshtml", allow_redirects=False)
        )
        if previously_authenticated and self._is_dashboard(login_page):
            self._authenticated = True
            return
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
        payload = self._login_payload(form, credentials)
        destination = urljoin(login_page.url, form.get("action") or login_page.url)
        if not self._same_origin(destination):
            raise AuthenticationError("Final Surge login action must be same-origin.")
        response = self._follow_login_redirects(
            self._request("POST", destination, data=payload, allow_redirects=False),
            credential_post=True,
        )
        self._require_authenticated(response)
        if not self._is_dashboard(response):
            raise AuthenticationError(
                "Final Surge login did not reach the verified dashboard. "
                "Interactive authentication or a changed page may require review."
            )

        self._authenticated = True

    @staticmethod
    def _login_payload(form: Tag, credentials: dict[str, str]) -> list[tuple[str, str]]:
        payload: list[tuple[str, str]] = []
        for field in form.select("input[name], select[name], textarea[name]"):
            if (
                not field["name"]
                or field.has_attr("disabled")
                or field.find_parent("fieldset", disabled=True) is not None
                or field["name"] in credentials
            ):
                continue
            name = str(field["name"])
            if field.name == "textarea":
                text = field.get_text().replace("\r\n", "\n").replace("\r", "\n")
                payload.append((name, text.replace("\n", "\r\n")))
                continue
            if field.name == "select":
                options = field.select("option")
                selected = [option for option in options if option.has_attr("selected")]
                if not field.has_attr("multiple"):
                    if selected:
                        selected = selected[-1:]
                    else:
                        selected = [
                            option
                            for option in options
                            if not option.has_attr("disabled")
                            and option.find_parent("optgroup", disabled=True) is None
                        ][:1]
                for option in selected:
                    if (
                        option.has_attr("disabled")
                        or option.find_parent("optgroup", disabled=True) is not None
                    ):
                        continue
                    payload.append(
                        (
                            name,
                            str(option.get("value", option.get_text(" ", strip=True))),
                        )
                    )
                continue
            field_type = str(field.get("type", "text")).casefold()
            if field_type in {"file", "submit", "button", "reset", "image"} or (
                field_type in {"checkbox", "radio"} and not field.has_attr("checked")
            ):
                continue
            default = "on" if field_type in {"checkbox", "radio"} else ""
            payload.append((name, str(field.get("value", default))))
        payload.extend(credentials.items())
        return payload

    def _follow_login_redirects(
        self, response: requests.Response, *, credential_post: bool = False
    ) -> requests.Response:
        for _ in range(5):
            if not 300 <= response.status_code < 400:
                return response
            location = response.headers.get("Location", "").strip()
            if not location:
                raise AuthenticationError("Final Surge login redirect has no Location.")
            redirect = urljoin(response.url, location)
            if not self._same_origin(redirect):
                raise AuthenticationError(
                    "Final Surge login redirect must be same-origin."
                )
            if credential_post and response.status_code in {307, 308}:
                raise AuthenticationError(
                    "Final Surge login POST requires credential replay, "
                    "which is refused."
                )
            # Never replay credentials on 307/308 or follow unchecked redirects.
            response = self._request("GET", redirect, allow_redirects=False)
            credential_post = False
        if 300 <= response.status_code < 400:
            raise AuthenticationError("Final Surge login has too many redirects.")
        return response

    @staticmethod
    def _is_dashboard(response: requests.Response) -> bool:
        # Preserve main's positive root/Dashboard invariant. Cookie presence or
        # an arbitrary non-login page is not sufficient proof of authentication.
        return (
            FinalSurgeClient._same_origin(response.url)
            and urlsplit(response.url).path in {"", "/"}
            and response.status_code < 300
            and "Dashboard" in response.text
            and BeautifulSoup(response.text, "html.parser").select_one(
                'form input[name="login_name"]'
            )
            is None
        )

    @staticmethod
    def _same_origin(url: str) -> bool:
        try:
            parsed = urlsplit(url)
            expected = urlsplit(BASE_URL)
            return (
                parsed.scheme.lower() == expected.scheme.lower() == "https"
                and parsed.hostname == expected.hostname
                and (parsed.port if parsed.port is not None else 443)
                == (expected.port if expected.port is not None else 443)
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
        if (
            "login.cshtml" in response.url
            or BeautifulSoup(response.text, "html.parser").select_one(
                'form input[name="login_name"]'
            )
            is not None
        ):
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
