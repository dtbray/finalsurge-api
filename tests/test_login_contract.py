import pytest
import requests
import responses
from bs4 import BeautifulSoup

from finalsurge_api import AuthenticationError, FinalSurgeClient
from finalsurge_api.client import BASE_URL


def test_form_payload_includes_selects_and_textareas():
    form = BeautifulSoup(
        """<form>
        <select name="single"><option disabled>skip</option>
            <option value="first">First</option></select>
        <select name="many" multiple><option value="a" selected>A</option>
            <option value="b" selected>B</option><option value="no">No</option>
            <optgroup disabled>
                <option value="blocked" selected>Blocked</option></optgroup>
        </select>
        <select name="empty" multiple><option value="no">No</option></select>
        <select name="disabled" disabled><option selected>No</option></select>
        <select name="placeholder"><option disabled selected>Pick one</option>
            <option value="not-selected">Other</option></select>
        <textarea name="token">line1\nline2</textarea>
        <textarea name="disabled-text" disabled>No</textarea>
    </form>""",
        "html.parser",
    ).select_one("form")
    payload = FinalSurgeClient._login_payload(form, {"login_name": "fixture-user"})
    assert payload == [
        ("single", "first"),
        ("many", "a"),
        ("many", "b"),
        ("token", "line1\r\nline2"),
        ("login_name", "fixture-user"),
    ]


@pytest.mark.parametrize("status", [307, 308])
@responses.activate
def test_login_post_refuses_credential_replay_with_distinct_error(status):
    responses.get(
        BASE_URL + "login.cshtml", body='<form><input name="login_name"></form>'
    )
    responses.post(
        BASE_URL + "login.cshtml", status=status, headers={"Location": "/continue"}
    )
    with pytest.raises(AuthenticationError, match="credential replay"):
        FinalSurgeClient(
            "fixture-user", "fixture-password", min_request_interval=0
        ).login()
    assert len(responses.calls) == 2


@responses.activate
def test_fresh_client_cannot_trust_anonymous_dashboard_even_with_cookie():
    responses.get(BASE_URL + "login.cshtml", status=302, headers={"Location": "/"})
    responses.get(BASE_URL, body="Dashboard marketing landing page")
    client = FinalSurgeClient(
        "fixture-user", "fixture-password", min_request_interval=0
    )
    client.session.cookies.set("analytics", "synthetic")
    with pytest.raises(AuthenticationError, match="form was not found"):
        client.login()
    assert not client._authenticated
    assert len(responses.calls) == 2


def test_authentication_check_uses_real_form_controls_not_script_or_comments():
    response = requests.Response()
    response.url = BASE_URL
    response.status_code = 200
    response._content = (
        b'Dashboard<!-- login_name --><script>const login_name = "";</script>'
    )
    FinalSurgeClient._require_authenticated(response)
    assert FinalSurgeClient._is_dashboard(response)
    response._content = b'Dashboard<form><input name="login_name"></form>'
    with pytest.raises(AuthenticationError, match="missing or expired"):
        FinalSurgeClient._require_authenticated(response)
    assert not FinalSurgeClient._is_dashboard(response)
