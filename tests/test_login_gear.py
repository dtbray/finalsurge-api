from datetime import date
from urllib.parse import parse_qs

import pytest
import responses

from finalsurge_api import AuthenticationError, Bike, FinalSurgeClient, Shoe
from finalsurge_api.client import BASE_URL


@responses.activate
def test_login_preserves_hidden_inputs_and_follows_same_origin_redirect():
    responses.get(
        BASE_URL + "login.cshtml",
        body="""
        <form action="ignored"><input name="search"></form>
        <form action="/login.cshtml"><input name="login_name">
        <input type="hidden" name="csrf" value="synthetic-token"></form>
    """,
    )
    responses.post(
        BASE_URL + "login.cshtml", status=302, headers={"Location": "/Calendar.cshtml"}
    )
    responses.get(BASE_URL + "Calendar.cshtml", body="Calendar")
    FinalSurgeClient("fixture-user", "fixture-password", min_request_interval=0).login()
    payload = parse_qs(responses.calls[1].request.body)
    assert payload["csrf"] == ["synthetic-token"]
    assert payload["login_name"] == ["fixture-user"]
    assert payload["login_password"] == ["fixture-password"]
    assert len(responses.calls) == 3


@pytest.mark.parametrize(
    "action",
    [
        "https://other.invalid/login",
        "//other.invalid/login",
        "http://log.finalsurge.com/login",
    ],
)
@responses.activate
def test_login_rejects_off_origin_action_before_post(action):
    responses.get(
        BASE_URL + "login.cshtml",
        body=f'<form action="{action}"><input name="login_name"></form>',
    )
    with pytest.raises(AuthenticationError, match="same-origin"):
        FinalSurgeClient(
            "fixture-user", "fixture-password", min_request_interval=0
        ).login()
    assert len(responses.calls) == 1


@responses.activate
def test_login_rejects_off_origin_redirect_without_following():
    responses.get(
        BASE_URL + "login.cshtml", body='<form><input name="login_name"></form>'
    )
    responses.post(
        BASE_URL + "login.cshtml",
        status=307,
        headers={"Location": "https://other.invalid/login"},
    )
    with pytest.raises(AuthenticationError, match="same-origin"):
        FinalSurgeClient(
            "fixture-user", "fixture-password", min_request_interval=0
        ).login()
    assert len(responses.calls) == 2


@responses.activate
def test_login_requires_form():
    responses.get(BASE_URL + "login.cshtml", body="No form")
    with pytest.raises(AuthenticationError, match="not found"):
        FinalSurgeClient(
            "fixture-user", "fixture-password", min_request_interval=0
        ).login()
    assert len(responses.calls) == 1


@pytest.mark.parametrize(
    "gear,method,path,extra",
    [
        (
            Shoe(
                "Fixture shoe",
                brand="Saucony",
                start_distance=12,
                purchase_date=date(2026, 1, 2),
                size=9,
            ),
            "create_shoe",
            "EquipmentShoes.cshtml",
            {"ShoeSize": ["9"], "btnSubmit": ["Add Shoe"]},
        ),
        (
            Bike(
                "Fixture bike",
                brand="Saucony",
                start_distance=12,
                purchase_date=date(2026, 1, 2),
                track_distance=False,
            ),
            "create_bike",
            "EquipmentBikes.cshtml",
            {"TrackDist": ["False"], "btnSubmit": ["Add Bike"]},
        ),
    ],
)
@responses.activate
def test_opted_in_gear_payload_is_offline(gear, method, path, extra):
    responses.get(
        BASE_URL + path,
        body=(
            '<select name="ShoeBrand">'
            '<option value="brand-id">Saucony</option></select>'
        ),
    )
    responses.post(BASE_URL + path, body="Created")
    client = FinalSurgeClient(
        "fixture-user", "fixture-password", min_request_interval=0
    )
    getattr(client, method)(gear, allow_writes=True)
    payload = parse_qs(responses.calls[1].request.body, keep_blank_values=True)
    assert payload["ShoeName"] == [gear.name]
    assert payload["ShoeBrand"] == ["brand-id"]
    assert payload["ShoeDate"] == ["1/2/2026"]
    assert payload["StartDist"] == ["12"]
    assert payload["DistType"] == ["mi"]
    for key, value in extra.items():
        assert payload[key] == value


def test_date_format_avoids_platform_strftime():
    class PortableDate:
        month = 1
        day = 2
        year = 2026

        def strftime(self, _):
            raise AssertionError("Platform-dependent strftime is forbidden")

    assert FinalSurgeClient._format_date(PortableDate()) == "1/2/2026"
    assert FinalSurgeClient._format_date(None) == ""
