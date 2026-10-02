from datetime import date
from urllib.parse import parse_qs

import pytest
import responses

from finalsurge_api import AuthenticationError, FinalSurgeClient, PlannedWorkout
from finalsurge_api.client import BASE_URL

LOGIN_FORM = """<form action="/login.cshtml"><input name="login_name">
<input type="hidden" name="csrf" value="synthetic-token">
<input type="hidden" name="repeat" value="a">
<input type="hidden" name="repeat" value="b">
<input type="hidden" name="disabled" value="no" disabled>
<fieldset disabled><input type="hidden" name="fieldset" value="no"></fieldset>
<input type="text" name="auxiliary" value="visible-step">
<input type="Hidden" name="mixed_case" value="hidden-step">
<input type="checkbox" name="checked_box" checked>
<input type="radio" name="checked_radio" value="chosen" checked>
<input type="checkbox" name="unchecked" value="no">
<input type="radio" name="radio" value="no">
<input type="submit" name="submit" value="no">
<input type="file" name="file">
</form>"""


def client():
    return FinalSurgeClient("fixture-user", "fixture-password", min_request_interval=0)


@responses.activate
def test_login_preserves_repeated_hidden_fields_but_not_non_data_controls():
    responses.get(BASE_URL + "login.cshtml", body=LOGIN_FORM)
    responses.post(BASE_URL + "login.cshtml", status=302, headers={"Location": "/"})
    responses.get(BASE_URL, body="Dashboard")
    client().login()
    payload = parse_qs(responses.calls[1].request.body)
    assert payload["csrf"] == ["synthetic-token"]
    assert payload["repeat"] == ["a", "b"]
    assert payload["login_name"] == ["fixture-user"]
    assert payload["login_password"] == ["fixture-password"]
    assert payload["page_redirect"] == ["/"]
    assert payload["auxiliary"] == ["visible-step"]
    assert payload["mixed_case"] == ["hidden-step"]
    assert payload["checked_box"] == ["on"]
    assert payload["checked_radio"] == ["chosen"]
    assert (
        not {"disabled", "fieldset", "unchecked", "radio", "submit", "file"}
        & payload.keys()
    )
    assert len(responses.calls) == 3


@pytest.mark.parametrize(
    "action",
    [
        "https://other.invalid/login",
        "//other.invalid/login",
        "http://log.finalsurge.com/login",
        "https://log.finalsurge.com:444/login",
        "https://user@log.finalsurge.com/login",
        "https://log.finalsurge.com:bad/login",
    ],
)
@responses.activate
def test_login_rejects_off_origin_or_invalid_action_before_post(action):
    responses.get(
        BASE_URL + "login.cshtml",
        body=f'<form action="{action}"><input name="login_name"></form>',
    )
    with pytest.raises(AuthenticationError, match="same-origin"):
        client().login()
    assert len(responses.calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://LOG.FINALSURGE.COM/login.cshtml",
        "https://log.finalsurge.com:443/login.cshtml",
    ],
)
def test_same_origin_normalizes_hostname_and_default_port(url):
    assert FinalSurgeClient._same_origin(url)


@responses.activate
def test_login_rejects_off_origin_redirect_without_following():
    responses.get(BASE_URL + "login.cshtml", body=LOGIN_FORM)
    responses.post(
        BASE_URL + "login.cshtml",
        status=307,
        headers={"Location": "https://other.invalid/login"},
    )
    with pytest.raises(AuthenticationError, match="same-origin"):
        client().login()
    assert len(responses.calls) == 2


@responses.activate
def test_login_rejects_off_origin_second_redirect_without_following():
    responses.get(BASE_URL + "login.cshtml", body=LOGIN_FORM)
    responses.post(
        BASE_URL + "login.cshtml", status=302, headers={"Location": "/middle"}
    )
    responses.get(
        BASE_URL + "middle", status=302, headers={"Location": "https://other.invalid/"}
    )
    with pytest.raises(AuthenticationError, match="same-origin"):
        client().login()
    assert len(responses.calls) == 3


@pytest.mark.parametrize("location", [None, "", "   "])
@responses.activate
def test_login_rejects_missing_redirect_location(location):
    responses.get(BASE_URL + "login.cshtml", body=LOGIN_FORM)
    headers = {} if location is None else {"Location": location}
    responses.post(BASE_URL + "login.cshtml", status=302, headers=headers)
    with pytest.raises(AuthenticationError, match="no Location"):
        client().login()
    assert len(responses.calls) == 2


@pytest.mark.parametrize(
    "destination,body", [("/", "Maintenance"), ("/mfa", "Enter OTP")]
)
@responses.activate
def test_login_requires_positive_dashboard_confirmation(destination, body):
    responses.get(BASE_URL + "login.cshtml", body=LOGIN_FORM)
    responses.post(
        BASE_URL + "login.cshtml", status=302, headers={"Location": destination}
    )
    responses.get(BASE_URL.rstrip("/") + destination, body=body)
    with pytest.raises(AuthenticationError, match="verified dashboard"):
        client().login()


@responses.activate
def test_login_requires_form():
    responses.get(BASE_URL + "login.cshtml", body="No form")
    with pytest.raises(AuthenticationError, match="not found"):
        client().login()
    assert len(responses.calls) == 1


def test_date_format_avoids_platform_strftime():
    class PortableDate:
        month = 1
        day = 2
        year = 2026

        def strftime(self, _):
            raise AssertionError("Platform-dependent strftime is forbidden")

    assert FinalSurgeClient._format_date(PortableDate()) == "1/2/2026"
    assert FinalSurgeClient._format_date(None) == ""
    assert (
        client()._calendar_payload(PlannedWorkout(date(2026, 1, 2), "Fixture"))[
            "WorkoutDate"
        ]
        == "1/2/2026"
    )
