# Final Surge API (unofficial)

This is a small personal-automation client for Final Surge's authenticated web
calendar. It is **not** an official Final Surge API and may require maintenance
when their site changes.

It deliberately defaults to read-only behavior. Workout creation is enabled
only by passing `allow_writes=True` at the call site.

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
