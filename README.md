# Final Surge API (unofficial)

This is a small personal-automation client for Final Surge's authenticated web
calendar. It is **not** an official Final Surge API and may require maintenance
when their site changes.

It deliberately defaults to read-only behavior. Workout creation is enabled
only by passing `allow_writes=True` at the call site.

Login follows at most five same-origin HTTPS redirects per request phase and
never resubmits credentials on redirects. It retains the existing positive
success contract: the origin root page must contain `Dashboard` and no login
form. A cookie alone or an unfamiliar landing page is not proof of success.
MFA or a changed page requires interactive authentication or a reviewed client
update, rather than silently claiming an authenticated session. Shoe/bike
creation is not supported until form provenance and write confirmation are
independently established (see issue #6).

```python
from datetime import date
from finalsurge_api import FinalSurgeClient, PlannedWorkout

client = FinalSurgeClient(username, password)
client.login()
print(client.calendar(date.today()))  # read-only

client.create_planned_workout(
    PlannedWorkout(date(2026, 10, 1), "Easy run", distance_miles=5),
    allow_writes=True,
)
```

For the Homelab, load credentials directly from 1Password instead of copying
them into an environment file:

```python
client = FinalSurgeClient.from_1password()
client.login()
library = client.list_library()
client.schedule_library_workout(library[0], date(2026, 8, 15), allow_writes=True)
```

Keep credentials in the Homelab 1Password vault (`log.finalsurge.com`); do not
put them in source control or environment files checked into git. See
[CONTRIBUTING.md](CONTRIBUTING.md) for development checks and
[HERMES.md](HERMES.md) for the agent collaboration contract.

## Strava gear reporting

`StravaClient` is read-only. It uses Strava's official API to fetch your shoes,
the lifetime mileage Strava assigns to each shoe, and an activity-window mileage
breakdown. Create a Strava API application and grant an OAuth token
`profile:read_all` and `activity:read_all`; keep its current short-lived access
token in the Homelab 1Password item `Strava API`, field `access_token`.

```python
from datetime import date
from pathlib import Path

from finalsurge_api import StravaClient

client = StravaClient.from_1password()
report = client.gear_report(after=date(2026, 1, 1))
client.export_gear_report_csv(report, Path("strava-shoe-mileage.csv"))
```

The CSV includes lifetime mileage, selected-period mileage, and the number of
activities assigned to each shoe. Activities assigned to a retired/deleted shoe
are retained as an explicit `Unknown or retired shoe` row rather than dropped.
