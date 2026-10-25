"""Switches exposed by the bed."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AiDreamRuntimeData
from .const import SNAPSHOT_CHILD_LOCK, SNAPSHOT_NIGHT_LIGHT
from .coordinator import AiDreamCoordinator
from .entity import AiDreamEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: AiDreamRuntimeData = entry.runtime_data
    coordinator = runtime.coordinator
    state = coordinator.data
    if state is None:
        return

    entities: list[AiDreamEntity] = []
    if SNAPSHOT_NIGHT_LIGHT in state.raw:
        entities.append(AiDreamNightLightSwitch(coordinator))
    if SNAPSHOT_CHILD_LOCK in state.raw:
        entities.append(AiDreamChildLockSwitch(coordinator))
    async_add_entities(entities)


class AiDreamNightLightSwitch(AiDreamEntity, SwitchEntity):
    """Under-bed light switch.

    The cloud stores the complete light program as a zero-padded string:
    ``<on><start HH><start MM><end HH><end MM>[<brightness>]``.
    """

    _attr_translation_key = "night_light"
    _attr_icon = "mdi:lightbulb-outline"

    def __init__(self, coordinator: AiDreamCoordinator) -> None:
        super().__init__(coordinator, "night_light")

    @property
    def _value(self) -> str | None:
        value = (
            self.coordinator.data.raw.get(SNAPSHOT_NIGHT_LIGHT)
            if self.coordinator.data
            else None
        )
        return value if isinstance(value, str) else None

    @property
    def is_on(self) -> bool | None:
        value = self._value
        if not value:
            return None
        if value[0] != "1":
            return False
        if len(value) >= 12:
            try:
                return int(value[9:12]) > 0
            except ValueError:
                return True
        return True

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)

    async def _async_set(self, on: bool) -> None:
        value = self._value or "000000000"
        enabled = "1" if on else "0"
        await self.coordinator.async_set_property(
            SNAPSHOT_NIGHT_LIGHT, enabled + value[1:]
        )
        await self.coordinator.async_request_refresh()


class AiDreamChildLockSwitch(AiDreamEntity, SwitchEntity):
    """Child lock switch."""

    _attr_translation_key = "child_lock"
    _attr_icon = "mdi:lock-outline"

    def __init__(self, coordinator: AiDreamCoordinator) -> None:
        super().__init__(coordinator, "child_lock")

    @property
    def is_on(self) -> bool | None:
        value = (
            self.coordinator.data.raw.get(SNAPSHOT_CHILD_LOCK)
            if self.coordinator.data
            else None
        )
        try:
            return int(float(value)) != 0
        except (TypeError, ValueError):
            return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(0)

    async def _async_set(self, value: int) -> None:
        await self.coordinator.async_set_property(SNAPSHOT_CHILD_LOCK, value)
        await self.coordinator.async_request_refresh()
