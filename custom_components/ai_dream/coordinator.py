"""State coordinator for AI Dream beds."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AiDreamApi, AiDreamApiError, AiDreamAuthError, Device
from .const import (
    CONF_GID,
    CONF_PASSWORD,
    CONF_PHONE,
    CONF_TOKEN,
    CONF_UID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PROP_HEAD_ANGLE,
    PROP_LEG_ANGLE,
    PROP_WAIST_ANGLE,
    SIDE_PREFIXES,
    SNAPSHOT_HEAD_ANGLE,
    SNAPSHOT_LEG_ANGLE,
    SNAPSHOT_ON_BED,
    SNAPSHOT_WAIST_ANGLE,
)

_LOGGER = logging.getLogger(__name__)
PENDING_TARGET_TTL = 180.0
AUTH_REJECT_CODES = {"1100", "1300", "401", "403"}


async def async_try_relogin(
    hass: HomeAssistant,
    entry: ConfigEntry,
    api: AiDreamApi,
    stale_token: str | None = None,
) -> bool:
    """Refresh an expired token once, serialising concurrent attempts.

    Returns False when the stored credentials were rejected. Raises
    ``UpdateFailed`` for transport/server errors so polling can recover later
    instead of forcing the user through re-authentication.
    """
    phone = entry.data.get(CONF_PHONE)
    password = entry.data.get(CONF_PASSWORD)
    if not phone or not password:
        return False

    token_before = stale_token if stale_token is not None else api.token
    async with api.auth_lock:
        if api.token != token_before:
            return True
        try:
            await api.login_password(phone, password)
        except AiDreamAuthError:
            return False
        except AiDreamApiError as err:
            if err.code in AUTH_REJECT_CODES:
                return False
            raise UpdateFailed(f"Re-login failed: {err}") from err

        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_TOKEN: api.token,
                CONF_UID: api.uid,
                CONF_GID: api.gid,
            },
        )
        return True


def _lookup(state: dict[str, Any], key: str) -> Any:
    if key in state:
        return state[key]
    for prefix in SIDE_PREFIXES:
        if prefix + key in state:
            return state[prefix + key]
    return None


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in ("1", "true", "on", "open"):
        return True
    if text in ("0", "false", "off", "close", ""):
        return False
    return None


@dataclass
class BedState:
    """Decoded bed snapshot."""

    head: int | None = None
    waist: int | None = None
    leg: int | None = None
    head_max: int = 60
    waist_max: int = 0
    leg_max: int = 45
    on_bed: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> BedState:
        support = snapshot.get("FunctionSupport")
        support = support if isinstance(support, dict) else {}
        return cls(
            head=_as_int(_lookup(snapshot, SNAPSHOT_HEAD_ANGLE)),
            waist=_as_int(_lookup(snapshot, SNAPSHOT_WAIST_ANGLE)),
            leg=_as_int(_lookup(snapshot, SNAPSHOT_LEG_ANGLE)),
            head_max=_as_int(support.get("HeadAngleMax")) or 60,
            waist_max=_as_int(support.get("WaistAngleMax")) or 0,
            leg_max=_as_int(support.get("LegAngleMax")) or 45,
            on_bed=_as_bool(_lookup(snapshot, SNAPSHOT_ON_BED)),
            raw=snapshot,
        )

    def angle(self, prop: str) -> int | None:
        if prop == PROP_HEAD_ANGLE:
            return self.head
        if prop == PROP_WAIST_ANGLE:
            return self.waist
        if prop == PROP_LEG_ANGLE:
            return self.leg
        return None

    def max_angle(self, prop: str) -> int:
        if prop == PROP_HEAD_ANGLE:
            return self.head_max
        if prop == PROP_WAIST_ANGLE:
            return self.waist_max
        return self.leg_max

    def has_waist(self) -> bool:
        return self.waist_max > 0 or bool(self.waist)


class AiDreamCoordinator(DataUpdateCoordinator[BedState]):
    """Poll the AI Dream cloud for the bed snapshot."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: AiDreamApi,
        device: Device,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {device.name}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.entry = entry
        self.api = api
        self.device = device
        self._angle_lock = asyncio.Lock()
        self._pending_targets: dict[str, tuple[int, float]] = {}

    def _clear_confirmed_targets(self, state: BedState, started_at: float) -> None:
        """Drop targets confirmed by a snapshot started after they were sent."""
        now = monotonic()
        for prop, (value, sent_at) in list(self._pending_targets.items()):
            expired = now - sent_at > PENDING_TARGET_TTL
            confirmed = sent_at <= started_at and state.angle(prop) == value
            if expired or confirmed:
                self._pending_targets.pop(prop, None)

    async def _async_fetch_state(self, started_at: float) -> BedState:
        token = self.api.token
        try:
            snapshot = await self.api.get_device_state(self.device.did)
        except AiDreamAuthError as err:
            if not await async_try_relogin(
                self.hass, self.entry, self.api, stale_token=token
            ):
                raise ConfigEntryAuthFailed("AI Dream token expired") from err
            try:
                snapshot = await self.api.get_device_state(self.device.did)
            except AiDreamAuthError as retry_err:
                raise ConfigEntryAuthFailed("AI Dream token expired") from retry_err
            except AiDreamApiError as retry_err:
                raise UpdateFailed(str(retry_err)) from retry_err
        except AiDreamApiError as err:
            raise UpdateFailed(str(err)) from err

        try:
            state = BedState.from_snapshot(snapshot)
        except (TypeError, ValueError) as err:
            raise UpdateFailed(f"Unexpected snapshot: {err}") from err
        self._clear_confirmed_targets(state, started_at)
        return state

    async def _async_update_data(self) -> BedState:
        return await self._async_fetch_state(monotonic())

    async def async_set_angles(
        self,
        *,
        head: int | None = None,
        waist: int | None = None,
        leg: int | None = None,
        mode_ctrl: int = 0,
    ) -> None:
        requested = {
            PROP_HEAD_ANGLE: head,
            PROP_WAIST_ANGLE: waist,
            PROP_LEG_ANGLE: leg,
        }
        async with self._angle_lock:
            now = monotonic()
            if any(
                now - sent_at > PENDING_TARGET_TTL and requested[prop] is None
                for prop, (_, sent_at) in self._pending_targets.items()
            ):
                await self.async_refresh()
                if not self.last_update_success:
                    error = self.last_exception
                    if isinstance(error, ConfigEntryAuthFailed):
                        self.entry.async_start_reauth(self.hass)
                        raise error
                    if isinstance(error, HomeAssistantError):
                        raise error
                    raise HomeAssistantError(
                        f"Could not refresh bed state: {error}"
                    ) from error
                state = self.data or BedState()
            else:
                state = self.data or BedState()

            now = monotonic()
            targets: dict[str, int] = {}
            for prop, value in requested.items():
                if value is not None:
                    targets[prop] = value
                    continue
                pending = self._pending_targets.get(prop)
                if pending is not None and now - pending[1] <= PENDING_TARGET_TTL:
                    targets[prop] = pending[0]
                else:
                    targets[prop] = state.angle(prop) or 0

            token = self.api.token
            try:
                await self.api.set_angles(
                    self.device.did,
                    head=targets[PROP_HEAD_ANGLE],
                    waist=targets[PROP_WAIST_ANGLE],
                    leg=targets[PROP_LEG_ANGLE],
                    mode_ctrl=mode_ctrl,
                )
            except AiDreamAuthError as err:
                if not await async_try_relogin(
                    self.hass, self.entry, self.api, stale_token=token
                ):
                    self.entry.async_start_reauth(self.hass)
                    raise ConfigEntryAuthFailed("AI Dream token expired") from err
                try:
                    await self.api.set_angles(
                        self.device.did,
                        head=targets[PROP_HEAD_ANGLE],
                        waist=targets[PROP_WAIST_ANGLE],
                        leg=targets[PROP_LEG_ANGLE],
                        mode_ctrl=mode_ctrl,
                    )
                except AiDreamAuthError as retry_err:
                    self.entry.async_start_reauth(self.hass)
                    raise ConfigEntryAuthFailed("AI Dream token expired") from retry_err
                except AiDreamApiError as retry_err:
                    raise HomeAssistantError(str(retry_err)) from retry_err
            except AiDreamApiError as err:
                raise HomeAssistantError(str(err)) from err

            sent_at = monotonic()
            requested_axes = {
                prop for prop, value in requested.items() if value is not None
            }
            for prop, value in targets.items():
                if prop in requested_axes or prop in self._pending_targets:
                    self._pending_targets[prop] = (value, sent_at)

    async def async_set_property(self, key: str, value: Any) -> None:
        token = self.api.token
        try:
            await self.api.set_property(self.device.did, key, value)
        except AiDreamAuthError as err:
            if not await async_try_relogin(
                self.hass, self.entry, self.api, stale_token=token
            ):
                self.entry.async_start_reauth(self.hass)
                raise ConfigEntryAuthFailed("AI Dream token expired") from err
            try:
                await self.api.set_property(self.device.did, key, value)
            except AiDreamAuthError as retry_err:
                self.entry.async_start_reauth(self.hass)
                raise ConfigEntryAuthFailed("AI Dream token expired") from retry_err
            except AiDreamApiError as retry_err:
                raise HomeAssistantError(str(retry_err)) from retry_err
        except AiDreamApiError as err:
            raise HomeAssistantError(str(err)) from err


class AiDreamReportCoordinator(DataUpdateCoordinator[dict[str, Any] | None]):
    """Fetch the daily sleep report less frequently than the bed state."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: AiDreamApi,
        device: Device,
        scan_interval: int = 1800,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {device.name} sleep report",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.entry = entry
        self.api = api
        self.device = device

    async def _async_update_data(self) -> dict[str, Any] | None:
        today = dt_util.now().date().isoformat()
        token = self.api.token
        try:
            return await self.api.get_day_report(self.device.did, today)
        except AiDreamAuthError as err:
            if not await async_try_relogin(
                self.hass, self.entry, self.api, stale_token=token
            ):
                raise ConfigEntryAuthFailed("AI Dream token expired") from err
            try:
                return await self.api.get_day_report(self.device.did, today)
            except AiDreamAuthError as retry_err:
                raise ConfigEntryAuthFailed("AI Dream token expired") from retry_err
            except AiDreamApiError as retry_err:
                raise UpdateFailed(str(retry_err)) from retry_err
        except AiDreamApiError as err:
            raise UpdateFailed(str(err)) from err
