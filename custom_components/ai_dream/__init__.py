"""The AI Dream integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import AiDreamApi, AiDreamApiError, AiDreamAuthError, Device
from .const import (
    CONF_DEVICE_NAME,
    CONF_DID,
    CONF_GID,
    CONF_PRODUCT_CODE,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_UID,
    DEFAULT_SCAN_INTERVAL,
)
from .coordinator import (
    AiDreamCoordinator,
    AiDreamReportCoordinator,
    async_try_relogin,
)

PLATFORMS = [
    "binary_sensor",
    "button",
    "cover",
    "number",
    "sensor",
    "switch",
]


@dataclass
class AiDreamRuntimeData:
    """Objects shared by the platforms."""

    api: AiDreamApi
    coordinator: AiDreamCoordinator
    report_coordinator: AiDreamReportCoordinator
    device: Device
    options: dict[str, Any]


type AiDreamConfigEntry = ConfigEntry[AiDreamRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: AiDreamConfigEntry) -> bool:
    """Set up AI Dream from a config entry."""
    session = async_get_clientsession(hass)
    api = AiDreamApi(session)
    api.restore_auth(
        entry.data[CONF_TOKEN],
        int(entry.data[CONF_UID]),
        entry.data.get(CONF_GID),
    )

    did = int(entry.data[CONF_DID])
    device = Device(
        did=did,
        name=entry.data.get(CONF_DEVICE_NAME) or "AI Dream Bed",
        product_code=entry.data.get(CONF_PRODUCT_CODE),
    )
    try:
        devices = await api.get_devices()
    except AiDreamAuthError as err:
        token = api.token
        try:
            relogged = await async_try_relogin(hass, entry, api, stale_token=token)
        except UpdateFailed as relogin_err:
            raise ConfigEntryNotReady(
                f"Could not refresh login: {relogin_err}"
            ) from relogin_err
        if not relogged:
            raise ConfigEntryAuthFailed("AI Dream token expired") from err
        try:
            devices = await api.get_devices()
        except AiDreamAuthError as retry_err:
            raise ConfigEntryAuthFailed("AI Dream token expired") from retry_err
        except AiDreamApiError as retry_err:
            raise ConfigEntryNotReady(
                f"Could not load device metadata: {retry_err}"
            ) from retry_err
    except AiDreamApiError as err:
        raise ConfigEntryNotReady(f"Could not load device metadata: {err}") from err

    device = next((item for item in devices if item.did == did), device)

    scan_interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    coordinator = AiDreamCoordinator(hass, entry, api, device, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    report_coordinator = AiDreamReportCoordinator(hass, entry, api, device)
    await report_coordinator.async_refresh()

    entry.runtime_data = AiDreamRuntimeData(
        api=api,
        coordinator=coordinator,
        report_coordinator=report_coordinator,
        device=device,
        options=dict(entry.options),
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AiDreamConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: AiDreamConfigEntry) -> None:
    """Reload only when options change, not when a token is persisted."""
    runtime = entry.runtime_data
    if runtime is not None and runtime.options == dict(entry.options):
        return
    await hass.config_entries.async_reload(entry.entry_id)
