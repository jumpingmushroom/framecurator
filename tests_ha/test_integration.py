from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

DOMAIN = "framecurator"
URL = "http://frame.test:8099"
FORM = {"name": "Phone Upstairs", CONF_URL: URL, CONF_TOKEN: "t", "width": 1080, "height": 2400}
STATE = {"changed_at": "2026-10-26T20:00:00+00:00", "asset_id": "a", "mode": "mixed", "bucket": "recent_30d",
         "date": "2026-10-03", "years_ago": 0, "place": "Tønsberg, Norway", "location": "Tønsberg, Norway", "captured_at": "2026-10-03T10:00:00+00:00",
         "caption": "Tønsberg, Norway · 3 Oct 2026", "next_change_at": "2026-10-26T20:15:00+00:00", "people": ["Kari", "Ola"],
         "paused": False, "interval_minutes": 15, "is_favorite": False, "is_pick": False, "can_go_back": True, "can_undo": False,
         "person": None, "album": None, "place_filter": None, "repeat_days": 14, "min_score": 6,
         "mix": {"on_this_day": 30, "favorites_picks": 20, "recent_30d": 35, "library": 15}}


async def test_config_flow_ok(hass, aioclient_mock):
    aioclient_mock.get(URL + "/state", json=STATE)
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], FORM | {CONF_URL: URL + "/"})
    assert r["type"] is FlowResultType.CREATE_ENTRY and r["title"] == "Phone Upstairs"
    assert r["data"] == {CONF_URL: URL, CONF_TOKEN: "t", "device": "phone-upstairs", "width": 1080, "height": 2400}


async def test_config_flow_errors(hass, aioclient_mock):
    aioclient_mock.get(URL + "/state", status=401)
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], FORM | {CONF_URL: URL, CONF_TOKEN: "bad"})
    assert r["errors"] == {"base": "invalid_auth"}
    aioclient_mock.clear_requests()
    aioclient_mock.get(URL + "/state", exc=OSError)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], FORM | {CONF_URL: URL})
    assert r["errors"] == {"base": "cannot_connect"}


async def setup(hass, aioclient_mock):
    aioclient_mock.get(URL + "/state", json=STATE)
    entry = MockConfigEntry(domain=DOMAIN, version=2, title="Frame Curator", unique_id=f"{URL}|default",
                            data={CONF_URL: URL, CONF_TOKEN: "t", "device": "default", "width": 1920, "height": 1200})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities_and_actions(hass, aioclient_mock):
    entry = await setup(hass, aioclient_mock)
    assert entry.state is ConfigEntryState.LOADED
    img = hass.states.get("image.frame_curator")
    assert img.attributes["place"] == img.attributes["location"] == "Tønsberg, Norway" and img.attributes["people"] == ["Kari", "Ola"]
    assert img.attributes["captured_at"] == "2026-10-03T10:00:00+00:00" and "asset_id" not in img.attributes
    assert hass.states.get("select.frame_curator_mode").state == "mixed"

    aioclient_mock.post(URL + "/next", json={**STATE, "asset_id": "b"})
    await hass.services.async_call("button", "press", {"entity_id": "button.frame_curator_skip"}, blocking=True)
    aioclient_mock.post(URL + "/block", json=STATE)
    await hass.services.async_call("button", "press", {"entity_id": "button.frame_curator_never_show_this"}, blocking=True)
    aioclient_mock.post(URL + "/mode", json={**STATE, "mode": "recent"})
    await hass.services.async_call("select", "select_option", {"entity_id": "select.frame_curator_mode", "option": "recent"}, blocking=True)
    posts = [(m, u.path) for m, u, *_ in aioclient_mock.mock_calls if m == "POST"]
    assert posts == [("POST", "/next"), ("POST", "/block"), ("POST", "/mode")]
    assert hass.states.get("select.frame_curator_mode").state == "recent"


async def test_image_bytes_use_token(hass, aioclient_mock, hass_client):
    await setup(hass, aioclient_mock)
    aioclient_mock.get(URL + "/image.jpg", content=b"JPEGDATA")
    client = await hass_client()
    token = hass.states.get("image.frame_curator").attributes["access_token"]
    r = await client.get(f"/api/image_proxy/image.frame_curator?token={token}")
    assert r.status == 200 and await r.read() == b"JPEGDATA"
    auth = next(h for m, u, b, h in aioclient_mock.mock_calls if u.path == "/image.jpg")
    assert auth["Authorization"] == "Bearer t"


async def test_unknown_place_is_none_not_empty(hass, aioclient_mock):
    aioclient_mock.get(URL + "/state", json={**STATE, "place": None, "location": None})
    await setup(hass, aioclient_mock)
    attrs = hass.states.get("image.frame_curator").attributes
    assert attrs["place"] is None and attrs["location"] is None


async def test_version_1_entry_migrates_to_the_default_device(hass, aioclient_mock):
    aioclient_mock.get(URL + "/state", json=STATE)
    old = MockConfigEntry(domain=DOMAIN, version=1, title="Frame Curator", unique_id=URL, data={CONF_URL: URL, CONF_TOKEN: "t"})
    old.add_to_hass(hass)
    await hass.config_entries.async_setup(old.entry_id)
    await hass.async_block_till_done()
    assert old.version == 2 and old.state is ConfigEntryState.LOADED and old.unique_id == f"{URL}|default"
    assert (old.data["device"], old.data["width"], old.data["height"]) == ("default", 1920, 1200)
    assert hass.states.get("image.frame_curator") is not None  # entity ids survive the migration
    assert aioclient_mock.mock_calls[0][1].query["device"] == "default"


async def test_two_devices_send_their_own_device_and_size(hass, aioclient_mock, hass_client):
    aioclient_mock.get(URL + "/state", json=STATE)
    aioclient_mock.get(URL + "/image.jpg", content=b"X")
    for title, device, w, h in (("Wallpanel", "wallpanel", 1920, 1200), ("Phone", "phone", 1080, 2400)):
        e = MockConfigEntry(domain=DOMAIN, version=2, title=title, unique_id=f"{URL}|{device}",
                            data={CONF_URL: URL, CONF_TOKEN: "t", "device": device, "width": w, "height": h})
        e.add_to_hass(hass)
        await hass.config_entries.async_setup(e.entry_id)
    await hass.async_block_till_done()
    client = await hass_client()
    for entity in ("image.wallpanel", "image.phone"):
        token = hass.states.get(entity).attributes["access_token"]
        assert (await client.get(f"/api/image_proxy/{entity}?token={token}")).status == 200
    images = {(u.query["device"], u.query["w"], u.query["h"]) for m, u, *_ in aioclient_mock.mock_calls if u.path == "/image.jpg"}
    assert images == {("wallpanel", "1920", "1200"), ("phone", "1080", "2400")}


async def test_caption_sensors(hass, aioclient_mock):
    await setup(hass, aioclient_mock)
    v = {e: hass.states.get(e).state for e in (
        "sensor.frame_curator_caption", "sensor.frame_curator_date", "sensor.frame_curator_place", "sensor.frame_curator_people",
        "sensor.frame_curator_years_ago", "sensor.frame_curator_next_change", "sensor.frame_curator_why_shown")}
    assert v == {"sensor.frame_curator_caption": "Tønsberg, Norway · 3 Oct 2026", "sensor.frame_curator_date": "2026-10-03",
                 "sensor.frame_curator_place": "Tønsberg, Norway", "sensor.frame_curator_people": "Kari, Ola",
                 "sensor.frame_curator_years_ago": "0", "sensor.frame_curator_next_change": "2026-10-26T20:15:00+00:00",
                 "sensor.frame_curator_why_shown": "Recent"}
    reg = er.async_get(hass)
    assert reg.async_get("sensor.frame_curator_caption").entity_category is None  # the one a card needs
    assert reg.async_get("sensor.frame_curator_place").entity_category is er.EntityCategory.DIAGNOSTIC


async def test_unknown_values_are_unknown_not_empty(hass, aioclient_mock):
    aioclient_mock.get(URL + "/state", json={**STATE, "place": None, "location": None, "people": [], "bucket": "library",
                                             "caption": "3 Oct 2026"})
    await setup(hass, aioclient_mock)
    assert hass.states.get("sensor.frame_curator_place").state == "unknown"
    assert hass.states.get("sensor.frame_curator_people").state == "unknown"
    assert hass.states.get("sensor.frame_curator_why_shown").state == "From the library"


async def test_photo_changed_event(hass, aioclient_mock):
    events = async_capture_events(hass, "framecurator_photo_changed")
    await setup(hass, aioclient_mock)
    assert events == []  # the first value after startup is not a change

    aioclient_mock.post(URL + "/next", json={**STATE, "changed_at": "2026-10-26T20:05:00+00:00", "place": "Oslo, Norway"})
    await hass.services.async_call("button", "press", {"entity_id": "button.frame_curator_skip"}, blocking=True)
    assert len(events) == 1
    assert events[0].data["device"] == "default" and events[0].data["place"] == "Oslo, Norway"
    assert "asset_id" not in events[0].data and "changed_at" not in events[0].data

    await hass.services.async_call("button", "press", {"entity_id": "button.frame_curator_skip"}, blocking=True)
    assert len(events) == 1  # same changed_at again: no new event

    aioclient_mock.clear_requests()
    aioclient_mock.get(URL + "/options", json={"people": [], "albums": [], "places": []})
    aioclient_mock.get(URL + "/state", json={**STATE, "changed_at": "2026-10-26T20:20:00+00:00", "place": "Bergen, Norway"})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=45))  # the server rotated: found by the next poll
    await hass.async_block_till_done()
    assert len(events) == 2 and events[1].data["place"] == "Bergen, Norway"


def posts(aioclient_mock):
    return [(u.path, b) for m, u, b, h in aioclient_mock.mock_calls if m == "POST"]


async def test_playback_and_feedback_buttons(hass, aioclient_mock):
    await setup(hass, aioclient_mock)
    assert hass.states.get("button.frame_curator_previous").state != "unavailable"  # can_go_back is true
    assert hass.states.get("button.frame_curator_undo_never_show").state == "unavailable"  # nothing to undo
    for path, entity in (("/previous", "previous"), ("/feedback", "more_like_this"), ("/feedback", "less_like_this")):
        aioclient_mock.post(URL + path, json=STATE)
        await hass.services.async_call("button", "press", {"entity_id": f"button.frame_curator_{entity}"}, blocking=True)
    assert posts(aioclient_mock) == [("/previous", None), ("/feedback", {"value": 1}), ("/feedback", {"value": -1})]


async def test_undo_is_available_when_the_api_says_so_and_calls_the_api(hass, aioclient_mock):
    aioclient_mock.get(URL + "/state", json={**STATE, "can_undo": True, "can_go_back": False})
    await setup(hass, aioclient_mock)
    assert hass.states.get("button.frame_curator_undo_never_show").state != "unavailable"
    assert hass.states.get("button.frame_curator_previous").state == "unavailable"
    aioclient_mock.post(URL + "/undo-block", json={**STATE, "can_undo": False})
    await hass.services.async_call("button", "press", {"entity_id": "button.frame_curator_undo_never_show"}, blocking=True)
    assert hass.states.get("button.frame_curator_undo_never_show").state == "unavailable"  # reply applied immediately


async def test_switches_and_interval(hass, aioclient_mock):
    await setup(hass, aioclient_mock)
    assert [hass.states.get(f"switch.frame_curator_{k}").state for k in ("pause", "favorite", "pick")] == ["off"] * 3
    assert hass.states.get("number.frame_curator_rotation_interval").state == "15"
    for key, field, path in (("pause", "paused", "/pause"), ("favorite", "is_favorite", "/favorite"), ("pick", "is_pick", "/pick")):
        aioclient_mock.post(URL + path, json={**STATE, field: True})
        await hass.services.async_call("switch", "turn_on", {"entity_id": f"switch.frame_curator_{key}"}, blocking=True)
        assert hass.states.get(f"switch.frame_curator_{key}").state == "on"
    aioclient_mock.post(URL + "/interval", json={**STATE, "interval_minutes": 30})
    await hass.services.async_call("number", "set_value", {"entity_id": "number.frame_curator_rotation_interval", "value": 30}, blocking=True)
    assert hass.states.get("number.frame_curator_rotation_interval").state == "30"
    assert posts(aioclient_mock) == [("/pause", {"on": True}), ("/favorite", {"on": True}), ("/pick", {"on": True}),
                                     ("/interval", {"minutes": 30})]


async def test_switch_turn_off(hass, aioclient_mock):
    aioclient_mock.get(URL + "/state", json={**STATE, "is_pick": True})
    await setup(hass, aioclient_mock)
    assert hass.states.get("switch.frame_curator_pick").state == "on"
    aioclient_mock.post(URL + "/pick", json={**STATE, "is_pick": False})
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.frame_curator_pick"}, blocking=True)
    assert hass.states.get("switch.frame_curator_pick").state == "off"
    assert posts(aioclient_mock) == [("/pick", {"on": False})]


async def test_api_refusal_becomes_a_readable_error(hass, aioclient_mock):
    await setup(hass, aioclient_mock)
    aioclient_mock.post(URL + "/pick", status=409, json={"detail": "album 'Frame - Picks' does not exist in Immich"})
    with pytest.raises(HomeAssistantError, match="does not exist in Immich"):
        await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.frame_curator_pick"}, blocking=True)
    assert hass.states.get("switch.frame_curator_pick").state == "off"  # nothing changed


async def test_new_entities_are_config_or_diagnostic_where_intended(hass, aioclient_mock):
    await setup(hass, aioclient_mock)
    reg = er.async_get(hass)
    assert reg.async_get("number.frame_curator_rotation_interval").entity_category is er.EntityCategory.CONFIG
    assert reg.async_get("switch.frame_curator_pause").entity_category is None


async def test_next_change_is_unknown_while_paused(hass, aioclient_mock):
    aioclient_mock.get(URL + "/state", json={**STATE, "paused": True, "next_change_at": None})
    await setup(hass, aioclient_mock)
    assert hass.states.get("sensor.frame_curator_next_change").state == "unknown"
    assert hass.states.get("switch.frame_curator_pause").state == "on"


async def test_filter_selects_offer_the_servers_options_and_choosing_sets_the_mode(hass, aioclient_mock):
    await setup(hass, aioclient_mock)
    assert hass.states.get("select.frame_curator_person").attributes["options"] == ["Kari", "Ola"]
    assert hass.states.get("select.frame_curator_album").attributes["options"] == ["Holiday"]
    assert hass.states.get("select.frame_curator_place").attributes["options"] == ["Norway", "Oslo, Norway"]
    assert hass.states.get("select.frame_curator_person").state == "unknown"  # nothing chosen yet
    assert hass.states.get("select.frame_curator_mode").attributes["options"][-4:] == ["favorites", "person", "album", "place"]
    aioclient_mock.post(URL + "/filter", json={**STATE, "mode": "person", "person": "Kari"})
    await hass.services.async_call("select", "select_option", {"entity_id": "select.frame_curator_person", "option": "Kari"}, blocking=True)
    assert hass.states.get("select.frame_curator_person").state == "Kari"
    assert hass.states.get("select.frame_curator_mode").state == "person"
    assert posts(aioclient_mock) == [("/filter", {"kind": "person", "value": "Kari"})]


async def test_place_select_uses_its_own_state_field(hass, aioclient_mock):
    await setup(hass, aioclient_mock)
    aioclient_mock.post(URL + "/filter", json={**STATE, "mode": "place", "place_filter": "Oslo, Norway"})
    await hass.services.async_call("select", "select_option", {"entity_id": "select.frame_curator_place", "option": "Oslo, Norway"}, blocking=True)
    assert hass.states.get("select.frame_curator_place").state == "Oslo, Norway"
    assert hass.states.get("select.frame_curator_person").state == "unknown"
    assert posts(aioclient_mock) == [("/filter", {"kind": "place", "value": "Oslo, Norway"})]


async def test_tuning_numbers_show_the_server_values_and_send_changes(hass, aioclient_mock):
    await setup(hass, aioclient_mock)
    vals = {k: hass.states.get(f"number.frame_curator_{k}").state for k in (
        "mix_on_this_day", "mix_favorites_and_picks", "mix_recent", "mix_whole_library", "repeat_window", "minimum_vision_score_all_displays")}
    assert vals == {"mix_on_this_day": "30", "mix_favorites_and_picks": "20", "mix_recent": "35", "mix_whole_library": "15",
                    "repeat_window": "14", "minimum_vision_score_all_displays": "6"}
    for path in ("/settings", "/min-score"):
        aioclient_mock.post(URL + path, json={**STATE, "mix": {**STATE["mix"], "recent_30d": 40}, "repeat_days": 7, "min_score": 8})
    for entity, value in (("mix_recent", 40), ("repeat_window", 7), ("minimum_vision_score_all_displays", 8)):
        await hass.services.async_call("number", "set_value", {"entity_id": f"number.frame_curator_{entity}", "value": value}, blocking=True)
    assert posts(aioclient_mock) == [("/settings", {"mix": {"recent_30d": 40}, "repeat_days": None}),
                                     ("/settings", {"mix": None, "repeat_days": 7}), ("/min-score", {"value": 8})]
    assert hass.states.get("number.frame_curator_minimum_vision_score_all_displays").state == "8"
    reg = er.async_get(hass)
    assert reg.async_get("number.frame_curator_mix_recent").entity_category is er.EntityCategory.CONFIG


async def test_reevaluate_button_reports_through_an_event(hass, aioclient_mock):
    events = async_capture_events(hass, "framecurator_reevaluated")
    await setup(hass, aioclient_mock)
    summary = {"min_score": 8, "moved_to_yes": 0, "moved_to_no": 3, "left_alone": 1}
    aioclient_mock.post(URL + "/reevaluate", json=summary)
    await hass.services.async_call("button", "press", {"entity_id": "button.frame_curator_re_evaluate"}, blocking=True)
    assert [e.data for e in events] == [summary]
    assert er.async_get(hass).async_get("button.frame_curator_re_evaluate").entity_category is er.EntityCategory.CONFIG
