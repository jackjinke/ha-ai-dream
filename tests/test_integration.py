"""Integration tests for the AI Dream custom component."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ai_dream.api import (
    AiDreamApi,
    AiDreamApiError,
    AiDreamAuthError,
    Device,
)
from custom_components.ai_dream.const import PROP_HEAD_ANGLE
from custom_components.ai_dream.coordinator import BedState, async_try_relogin

DOMAIN = "ai_dream"
DID = 1234567
PHONE = "10000000000"

ENTRY_DATA = {
    "token": "token",
    "uid": 1001,
    "gid": 2002,
    "did": DID,
    "device_name": "Test Bed",
    "product_code": "E1SD",
    "phone": PHONE,
}

STATE = {
    "online": "1",
    "HeadAngle": "30",
    "LegAngle": "10",
    "WaistAngle": "0",
    "OnBed": "1",
    "NightLight": "000000000100",
    "ChildLock": "0",
    "FunctionSupport": {"HeadAngleMax": 60, "LegAngleMax": 45, "WaistAngleMax": 0},
}

ZERO_STATE = {**STATE, "HeadAngle": "0", "LegAngle": "0"}
HEAD2_STATE = {**ZERO_STATE, "HeadAngle": "2"}

REPORT = {
    "score": 95,
    "sleepTime": 570,
    "deep": {"value": 391},
    "light": {"value": 29},
    "rem": {"value": 150},
    "awake": {"value": 0},
    "heart_beat_avg": 63,
    "breath_avg": 13,
    "body_move": [{"value": 8}, {"value": 5}],
    "body_revolve": [{"value": 13}, {"value": 6}],
    "snore_count": [],
    "hrvResult": {"daySdnn": 60, "dayStress": 28, "dayFatigued": 53},
    "sleepQualityTagValue": "rested",
    "textTagValue": "advice",
    "tagKeys": ["TAG"],
    "time_start": 1792860037,
    "time_end": 1792896456,
}

DEVICE = Device(
    did=DID,
    name="Test Bed",
    mac="AA:BB:CC:DD:EE:FF",
    product_code="E1SD",
    online=True,
    patterns=[
        {
            "patternId": 1,
            "patternName": "Flat",
            "headAngle": 0,
            "legAngle": 0,
            "modeCtrl": 1,
        },
        {
            "patternId": 2,
            "patternName": "Zero pressure",
            "headAngle": 15,
            "legAngle": 35,
            "modeCtrl": 2,
        },
    ],
)


def _cloud_patches(state=STATE):
    return (
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_devices",
            AsyncMock(return_value=[DEVICE]),
        ),
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_device_state",
            AsyncMock(return_value=state),
        ),
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_day_report",
            AsyncMock(return_value=REPORT),
        ),
    )


@pytest.mark.asyncio
async def test_setup_and_control(hass, enable_custom_integrations):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id=str(DID))
    entry.add_to_hass(hass)

    patches = _cloud_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patch(
            "custom_components.ai_dream.api.AiDreamApi.set_angles", AsyncMock()
        ) as set_angles,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        registry = er.async_get(hass)
        cover_id = registry.async_get_entity_id("cover", DOMAIN, f"{DID}_head_angle")
        assert cover_id
        state = hass.states.get(cover_id)
        assert state.state == "open"
        assert state.attributes["current_position"] == 50
        assert state.attributes["friendly_name"].endswith("Head angle")

        sensor_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{DID}_report_sleep_score"
        )
        assert sensor_id
        assert hass.states.get(sensor_id).state == "95"

        await hass.services.async_call(
            "cover",
            "set_cover_position",
            {"entity_id": cover_id, "position": 50},
            blocking=True,
        )
        assert set_angles.await_args.kwargs["head"] == 30

        leg_cover_id = registry.async_get_entity_id("cover", DOMAIN, f"{DID}_leg_angle")
        assert leg_cover_id
        await hass.services.async_call(
            "cover",
            "set_cover_position",
            {"entity_id": leg_cover_id, "position": 50},
            blocking=True,
        )
        assert set_angles.await_args.kwargs["leg"] == 22

        number_id = registry.async_get_entity_id(
            "number", DOMAIN, f"{DID}_number_head_angle"
        )
        assert number_id
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": number_id, "value": 15},
            blocking=True,
        )
        assert set_angles.await_args.kwargs["head"] == 15

        with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "token": "new-token"}
            )
            await hass.async_block_till_done()
            reload.assert_not_awaited()

            hass.config_entries.async_update_entry(entry, options={"scan_interval": 60})
            await hass.async_block_till_done()
            reload.assert_awaited_once()


@pytest.mark.asyncio
async def test_pending_targets_merge(hass, enable_custom_integrations):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id=str(DID))
    entry.add_to_hass(hass)

    patches = _cloud_patches(ZERO_STATE)
    with (
        patches[0],
        patches[1],
        patches[2],
        patch(
            "custom_components.ai_dream.api.AiDreamApi.set_angles", AsyncMock()
        ) as set_angles,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = entry.runtime_data.coordinator
        await coordinator.async_set_angles(head=2)
        assert set_angles.await_args.kwargs["head"] == 2
        assert set_angles.await_args.kwargs["leg"] == 0

        await coordinator.async_set_angles(leg=2)
        assert set_angles.await_args.kwargs["head"] == 2
        assert set_angles.await_args.kwargs["leg"] == 2


@pytest.mark.asyncio
async def test_expired_pending_refreshes_before_sending(
    hass, enable_custom_integrations
):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id=str(DID))
    entry.add_to_hass(hass)
    get_state = AsyncMock(side_effect=[ZERO_STATE, HEAD2_STATE])

    with (
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_devices",
            AsyncMock(return_value=[DEVICE]),
        ),
        patch("custom_components.ai_dream.api.AiDreamApi.get_device_state", get_state),
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_day_report",
            AsyncMock(return_value=REPORT),
        ),
        patch(
            "custom_components.ai_dream.api.AiDreamApi.set_angles", AsyncMock()
        ) as set_angles,
        patch("custom_components.ai_dream.coordinator.PENDING_TARGET_TTL", -1),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = entry.runtime_data.coordinator
        await coordinator.async_set_angles(head=2)
        calls_after_first = set_angles.await_count

        await coordinator.async_set_angles(leg=2)
        assert set_angles.await_count == calls_after_first + 1
        assert set_angles.await_args.kwargs["head"] == 2
        assert set_angles.await_args.kwargs["leg"] == 2
        assert get_state.await_count >= 2

        # The fresh snapshot was published through the coordinator, so the
        # next command must not fall back to the pre-refresh angle.
        await coordinator.async_set_angles(leg=3)
        assert set_angles.await_args.kwargs["head"] == 2
        assert set_angles.await_args.kwargs["leg"] == 3


@pytest.mark.asyncio
async def test_explicit_target_survives_pre_send_snapshot(
    hass, enable_custom_integrations
):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id=str(DID))
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_devices",
            AsyncMock(return_value=[DEVICE]),
        ),
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_device_state",
            AsyncMock(return_value=ZERO_STATE),
        ),
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_day_report",
            AsyncMock(return_value=REPORT),
        ),
        patch(
            "custom_components.ai_dream.api.AiDreamApi.set_angles", AsyncMock()
        ) as set_angles,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = entry.runtime_data.coordinator
        await coordinator.async_set_angles(head=2)
        await coordinator.async_set_angles(head=0)
        assert coordinator._pending_targets[PROP_HEAD_ANGLE][0] == 0

        # A snapshot started before the second command reflects 0°, but it
        # must not confirm the new 0° target.
        before_command = coordinator._pending_targets[PROP_HEAD_ANGLE][1] - 10
        coordinator._clear_confirmed_targets(
            BedState.from_snapshot(ZERO_STATE), before_command
        )
        assert coordinator._pending_targets[PROP_HEAD_ANGLE][0] == 0

        await coordinator.async_set_angles(leg=2)
        assert set_angles.await_args.kwargs["head"] == 0


@pytest.mark.asyncio
async def test_forced_waist_has_positive_limit(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        options={"enable_waist": True},
        unique_id=str(DID),
    )
    entry.add_to_hass(hass)

    patches = _cloud_patches()
    with patches[0], patches[1], patches[2]:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        cover_id = registry.async_get_entity_id("cover", DOMAIN, f"{DID}_waist_angle")
        assert cover_id
        state = hass.states.get(cover_id)
        assert state.attributes["max_angle"] == 8
        assert state.attributes["current_position"] == 0


@pytest.mark.asyncio
async def test_cloud_connection_stays_readable(hass, enable_custom_integrations):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id=str(DID))
    entry.add_to_hass(hass)

    patches = _cloud_patches()
    with patches[0], patches[1], patches[2]:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{DID}_online"
        )
        assert entity_id
        assert hass.states.get(entity_id).state == "on"

        coordinator = entry.runtime_data.coordinator
        coordinator.last_update_success = False
        coordinator.async_update_listeners()
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == "off"


@pytest.mark.asyncio
async def test_relogin_error_classification(hass, enable_custom_integrations):
    entry = SimpleNamespace(data={"phone": PHONE, "password": "pw"})
    api = AiDreamApi(None)  # type: ignore[arg-type]
    api.token = "old"
    api.gid = 2002
    api.login_password = AsyncMock()

    api.login_password.side_effect = AiDreamApiError("-1", "timeout")
    with pytest.raises(UpdateFailed):
        await async_try_relogin(hass, entry, api)

    api.login_password.side_effect = AiDreamApiError("1300", "bad password")
    assert not await async_try_relogin(hass, entry, api)

    api.login_password = AsyncMock()
    api.token = "new"
    assert await async_try_relogin(hass, entry, api, stale_token="old")
    api.login_password.assert_not_awaited()


@pytest.mark.asyncio
async def test_config_flow(hass, enable_custom_integrations):
    async def fake_login(api: AiDreamApi, phone: str, code: str) -> None:
        api.token = "token"
        api.uid = 1001
        api.gid = 2002

    with (
        patch("custom_components.ai_dream.api.AiDreamApi.send_sms_code", AsyncMock()),
        patch(
            "custom_components.ai_dream.api.AiDreamApi.login_sms",
            fake_login,
        ),
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_devices",
            AsyncMock(return_value=[DEVICE]),
        ),
    ):
        flow = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert flow["type"] == "form"
        assert flow["step_id"] == "user"

        flow = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"phone": PHONE, "method": "sms"}
        )
        assert flow["step_id"] == "sms"

        flow = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"sms_code": "123456"}
        )
        assert flow["type"] == "create_entry"
        assert flow["data"]["did"] == DID


@pytest.mark.asyncio
async def test_device_metadata_after_relogin(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY_DATA, "password": "pw"},
        unique_id=str(DID),
    )
    entry.add_to_hass(hass)

    async def fake_login(api: AiDreamApi, phone: str, password: str) -> None:
        api.token = "fresh"
        api.uid = 1001
        api.gid = 2002

    get_devices = AsyncMock(side_effect=[AiDreamAuthError("expired"), [DEVICE]])

    with (
        patch("custom_components.ai_dream.api.AiDreamApi.get_devices", get_devices),
        patch("custom_components.ai_dream.api.AiDreamApi.login_password", fake_login),
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_device_state",
            AsyncMock(return_value=STATE),
        ),
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_day_report",
            AsyncMock(return_value=REPORT),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.LOADED
        assert entry.data["token"] == "fresh"
        assert entry.runtime_data.device.patterns == DEVICE.patterns

        registry = er.async_get(hass)
        button_id = registry.async_get_entity_id("button", DOMAIN, f"{DID}_preset_1")
        assert button_id


@pytest.mark.asyncio
async def test_report_relogin(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY_DATA, "password": "pw"},
        unique_id=str(DID),
    )
    entry.add_to_hass(hass)

    async def fake_login(api: AiDreamApi, phone: str, password: str) -> None:
        api.token = "fresh"

    report = AsyncMock(side_effect=[AiDreamAuthError("expired"), REPORT])

    with (
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_devices",
            AsyncMock(return_value=[DEVICE]),
        ),
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_device_state",
            AsyncMock(return_value=STATE),
        ),
        patch("custom_components.ai_dream.api.AiDreamApi.get_day_report", report),
        patch("custom_components.ai_dream.api.AiDreamApi.login_password", fake_login),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        sensor_id = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{DID}_report_sleep_score"
        )
        assert sensor_id
        assert hass.states.get(sensor_id).state == "95"
        assert report.await_count == 2


@pytest.mark.asyncio
async def test_setup_retry_on_relogin_transport_error(hass, enable_custom_integrations):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY_DATA, "password": "pw"},
        unique_id=str(DID),
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_devices",
            AsyncMock(side_effect=AiDreamAuthError("expired")),
        ),
        patch(
            "custom_components.ai_dream.api.AiDreamApi.login_password",
            AsyncMock(side_effect=AiDreamApiError("-1", "timeout")),
        ),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.asyncio
async def test_device_list_still_rejected_starts_reauth(
    hass, enable_custom_integrations
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY_DATA, "password": "pw"},
        unique_id=str(DID),
    )
    entry.add_to_hass(hass)

    async def fake_login(api: AiDreamApi, phone: str, password: str) -> None:
        api.token = "fresh"

    with (
        patch(
            "custom_components.ai_dream.api.AiDreamApi.get_devices",
            AsyncMock(
                side_effect=[AiDreamAuthError("expired"), AiDreamAuthError("expired")]
            ),
        ),
        patch("custom_components.ai_dream.api.AiDreamApi.login_password", fake_login),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert any(
        flow["handler"] == DOMAIN and flow.get("context", {}).get("source") == "reauth"
        for flow in flows
    )
