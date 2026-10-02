import pytest
import responses

from finalsurge_api import AuthenticationError, FinalSurgeClient
from finalsurge_api.client import BASE_URL


@responses.activate
def test_initial_login_page_redirect_is_followed_safely():
    responses.get(
        BASE_URL + "login.cshtml", status=302, headers={"Location": "/canonical-login"}
    )
    responses.get(
        BASE_URL + "canonical-login",
        body='<form action="/login.cshtml"><input name="login_name"></form>',
    )
    responses.post(BASE_URL + "login.cshtml", status=302, headers={"Location": "/"})
    responses.get(BASE_URL, body="Dashboard")
    FinalSurgeClient("fixture-user", "fixture-password", min_request_interval=0).login()
    assert len(responses.calls) == 4


@responses.activate
def test_already_authenticated_redirect_does_not_resubmit_credentials():
    responses.get(BASE_URL + "login.cshtml", status=302, headers={"Location": "/"})
    responses.get(BASE_URL, body="Dashboard")
    FinalSurgeClient("fixture-user", "fixture-password", min_request_interval=0).login()
    assert len(responses.calls) == 2
    assert all(call.request.method == "GET" for call in responses.calls)


@responses.activate
def test_initial_redirect_cannot_leave_origin():
    responses.get(
        BASE_URL + "login.cshtml",
        status=302,
        headers={"Location": "https://other.invalid/"},
    )
    with pytest.raises(AuthenticationError, match="same-origin"):
        FinalSurgeClient(
            "fixture-user", "fixture-password", min_request_interval=0
        ).login()
    assert len(responses.calls) == 1


@responses.activate
def test_login_redirect_budget_has_distinct_error():
    responses.get(BASE_URL + "login.cshtml", status=302, headers={"Location": "/loop"})
    responses.get(BASE_URL + "loop", status=302, headers={"Location": "/loop"})
    with pytest.raises(AuthenticationError, match="too many redirects"):
        FinalSurgeClient(
            "fixture-user", "fixture-password", min_request_interval=0
        ).login()
    assert len(responses.calls) == 6
    assert all(call.request.method == "GET" for call in responses.calls)


def test_same_origin_uses_configured_https_port(monkeypatch):
    monkeypatch.setattr(
        "finalsurge_api.client.BASE_URL", "https://staging.invalid:8443/"
    )
    assert FinalSurgeClient._same_origin("https://STAGING.INVALID:8443/login")
    assert not FinalSurgeClient._same_origin("https://staging.invalid/login")
    assert not FinalSurgeClient._same_origin("http://staging.invalid:8443/login")
