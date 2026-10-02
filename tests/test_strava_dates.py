from datetime import date, datetime, timedelta, timezone

import pytest

from finalsurge_api import StravaClient


@pytest.mark.parametrize("method", ["_epoch_start", "_epoch_end"])
@pytest.mark.parametrize("offset", [-7, 0, 5])
def test_epoch_preserves_aware_datetime_instant(method, offset):
    value = datetime(2026, 7, 1, 12, 30, tzinfo=timezone(timedelta(hours=offset)))
    assert getattr(StravaClient, method)(value) == int(value.timestamp())


def test_naive_date_window_remains_utc():
    assert StravaClient._epoch_start(date(2026, 7, 1)) == int(
        datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()
    )
    assert StravaClient._epoch_end(date(2026, 7, 1)) == int(
        datetime(2026, 7, 1, 23, 59, 59, tzinfo=timezone.utc).timestamp()
    )
