from __future__ import annotations

import csv
import subprocess
import threading
import time as clock
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

STRAVA_BASE_URL = "https://www.strava.com/api/v3/"
METERS_PER_MILE = 1609.344


class StravaError(RuntimeError):
    """The Strava API rejected or could not complete a request."""


class StravaAuthenticationError(StravaError):
    """The supplied OAuth access token is absent, expired, or insufficient."""


@dataclass(frozen=True)
class StravaGear:
    id: str
    name: str
    brand_name: str | None
    model_name: str | None
    lifetime_miles: float
    primary: bool


@dataclass(frozen=True)
class StravaActivity:
    id: int
    name: str
    sport_type: str
    started_at: datetime
    distance_miles: float
    gear_id: str | None


@dataclass(frozen=True)
class GearReport:
    gear: StravaGear
    activity_count: int
    period_miles: float


class StravaClient:
    """Read-only client for Strava athlete gear and activity reporting.

    Use an OAuth access token with ``profile:read_all`` and
    ``activity:read_all``. This client only issues GET requests.
    """

    def __init__(
        self,
        access_token: str,
        *,
        timeout: float = 20,
        min_request_interval: float = 0.5,
    ) -> None:
        if not access_token.strip():
            raise ValueError("A Strava OAuth access token is required.")
        self.timeout = timeout
        self.min_request_interval = min_request_interval
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0
        self.session = requests.Session()
        self.session.mount(
            "https://",
            HTTPAdapter(
                max_retries=Retry(
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
            ),
        )
        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "finalsurge-api/0.1 (personal gear reporting)",
            }
        )

    @classmethod
    def from_1password(
        cls,
        *,
        vault: str = "Homelab",
        item: str = "Strava API",
        field: str = "access_token",
    ) -> StravaClient:
        """Load a short-lived Strava access token into memory from 1Password."""
        return cls(cls._onepassword_field(item, vault, field))

    def list_shoes(self) -> list[StravaGear]:
        """Return all shoes in the authenticated athlete's Strava profile."""
        athlete = self._get("athlete")
        shoes = athlete.get("shoes", [])
        return [self._gear_from_payload(shoe) for shoe in shoes]

    def get_gear(self, gear_id: str) -> StravaGear:
        """Return a detailed gear record, including Strava's lifetime distance."""
        return self._gear_from_payload(self._get(f"gear/{gear_id}"))

    def list_activities(
        self,
        *,
        after: date | datetime | None = None,
        before: date | datetime | None = None,
    ) -> list[StravaActivity]:
        """List all athlete activities in an optional inclusive local-date window."""
        params: dict[str, int] = {"per_page": 200}
        if after is not None:
            params["after"] = self._epoch_start(after)
        if before is not None:
            params["before"] = self._epoch_end(before)

        activities: list[StravaActivity] = []
        page = 1
        while True:
            response = self._get("athlete/activities", params={**params, "page": page})
            if not isinstance(response, list):
                raise StravaError("Unexpected activities response from Strava.")
            activities.extend(self._activity_from_payload(item) for item in response)
            if len(response) < params["per_page"]:
                return activities
            page += 1

    def gear_report(
        self,
        *,
        after: date | datetime | None = None,
        before: date | datetime | None = None,
    ) -> list[GearReport]:
        """Join Strava shoes to activities and calculate reporting-window mileage."""
        activities_by_gear: dict[str, list[StravaActivity]] = {}
        for activity in self.list_activities(after=after, before=before):
            if activity.gear_id:
                activities_by_gear.setdefault(activity.gear_id, []).append(activity)

        reports = []
        for summary in self.list_shoes():
            gear = self.get_gear(summary.id)
            activities = activities_by_gear.pop(gear.id, [])
            reports.append(
                GearReport(
                    gear=gear,
                    activity_count=len(activities),
                    period_miles=round(
                        sum(item.distance_miles for item in activities), 2
                    ),
                )
            )
        for gear_id, activities in activities_by_gear.items():
            reports.append(
                GearReport(
                    gear=StravaGear(
                        gear_id, "Unknown or retired shoe", None, None, 0, False
                    ),
                    activity_count=len(activities),
                    period_miles=round(
                        sum(item.distance_miles for item in activities), 2
                    ),
                )
            )
        return sorted(reports, key=lambda report: report.gear.name.lower())

    @staticmethod
    def export_gear_report_csv(reports: Iterable[GearReport], output: Path) -> None:
        """Write a stable, portable gear report without persisting any credentials."""
        with output.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=(
                    "gear_id",
                    "name",
                    "brand",
                    "model",
                    "is_primary",
                    "lifetime_miles",
                    "period_miles",
                    "activity_count",
                ),
            )
            writer.writeheader()
            for report in reports:
                writer.writerow(
                    {
                        "gear_id": report.gear.id,
                        "name": report.gear.name,
                        "brand": report.gear.brand_name or "",
                        "model": report.gear.model_name or "",
                        "is_primary": report.gear.primary,
                        "lifetime_miles": f"{report.gear.lifetime_miles:.2f}",
                        "period_miles": f"{report.period_miles:.2f}",
                        "activity_count": report.activity_count,
                    }
                )

    def _get(self, path: str, **kwargs: Any) -> Any:
        with self._request_lock:
            wait = self.min_request_interval - (
                clock.monotonic() - self._last_request_at
            )
            if wait > 0:
                clock.sleep(wait)
            self._last_request_at = clock.monotonic()
        response = self.session.get(
            urljoin(STRAVA_BASE_URL, path), timeout=self.timeout, **kwargs
        )
        if response.status_code in (401, 403):
            raise StravaAuthenticationError(
                "Strava rejected the OAuth token or its granted scopes."
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            raise StravaError(
                f"Strava request failed: HTTP {response.status_code}"
            ) from error
        return response.json()

    @staticmethod
    def _gear_from_payload(payload: dict[str, Any]) -> StravaGear:
        return StravaGear(
            id=str(payload["id"]),
            name=str(payload.get("name") or "Unnamed shoe"),
            brand_name=payload.get("brand_name"),
            model_name=payload.get("model_name"),
            lifetime_miles=round(
                float(payload.get("distance") or 0) / METERS_PER_MILE, 2
            ),
            primary=bool(payload.get("primary", False)),
        )

    @staticmethod
    def _activity_from_payload(payload: dict[str, Any]) -> StravaActivity:
        return StravaActivity(
            id=int(payload["id"]),
            name=str(payload.get("name") or "Unnamed activity"),
            sport_type=str(
                payload.get("sport_type") or payload.get("type") or "Unknown"
            ),
            started_at=datetime.fromisoformat(
                str(payload["start_date"]).replace("Z", "+00:00")
            ),
            distance_miles=float(payload.get("distance") or 0) / METERS_PER_MILE,
            gear_id=payload.get("gear_id"),
        )

    @staticmethod
    def _epoch_start(value: date | datetime) -> int:
        moment = (
            value if isinstance(value, datetime) else datetime.combine(value, time.min)
        )
        utc_moment = (
            moment.astimezone(timezone.utc)
            if moment.tzinfo is not None
            else moment.replace(tzinfo=timezone.utc)
        )
        return int(utc_moment.timestamp())

    @staticmethod
    def _epoch_end(value: date | datetime) -> int:
        moment = (
            value if isinstance(value, datetime) else datetime.combine(value, time.max)
        )
        utc_moment = (
            moment.astimezone(timezone.utc)
            if moment.tzinfo is not None
            else moment.replace(tzinfo=timezone.utc)
        )
        return int(utc_moment.timestamp())

    @staticmethod
    def _onepassword_field(item: str, vault: str, field: str) -> str:
        try:
            return subprocess.run(
                ["op", "item", "get", item, "--vault", vault, "--fields", field],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            raise StravaAuthenticationError(
                f"Could not load Strava field '{field}' from 1Password item '{item}'."
            ) from error
