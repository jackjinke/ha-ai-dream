"""Exact degree control for each motorised axis."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AiDreamRuntimeData
from .const import (
    AXES,
    CONF_ENABLE_WAIST,
    PROP_HEAD_ANGLE,
    PROP_LEG_ANGLE,
    PROP_WAIST_ANGLE,
    Axis,
)
from .coordinator import AiDreamCoordinator
from .entity import AiDreamEntity, supports_waist


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: AiDreamRuntimeData = entry.runtime_data
    coordinator = runtime.coordinator
    waist = supports_waist(
        coordinator, bool(entry.options.get(CONF_ENABLE_WAIST, False))
    )

    entities: list[AiDreamAngleNumber] = []
    for axis in AXES:
        if axis.prop == PROP_WAIST_ANGLE and not waist:
            continue
        entities.append(AiDreamAngleNumber(coordinator, axis))
    async_add_entities(entities)


class AiDreamAngleNumber(AiDreamEntity, NumberEntity):
    """Set an axis target in degrees."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1
    _attr_native_min_value = 0
    _attr_native_unit_of_measurement = "°"

    def __init__(self, coordinator: AiDreamCoordinator, axis: Axis) -> None:
        super().__init__(coordinator, f"number_{axis.key}")
        self._axis = axis
        self._attr_translation_key = axis.key
        self._attr_icon = axis.icon

    @property
    def native_max_value(self) -> float:
        if self.coordinator.data:
            reported = self.coordinator.data.max_angle(self._axis.prop)
            if reported > 0:
                return reported
        return self._axis.max_angle

    @property
    def native_value(self) -> float | None:
        return (
            self.coordinator.data.angle(self._axis.prop)
            if self.coordinator.data
            else None
        )

    async def async_set_native_value(self, value: float) -> None:
        angle = max(0, min(round(value), int(self.native_max_value)))
        if self._axis.prop == PROP_HEAD_ANGLE:
            await self.coordinator.async_set_angles(head=angle)
        elif self._axis.prop == PROP_LEG_ANGLE:
            await self.coordinator.async_set_angles(leg=angle)
        else:
            await self.coordinator.async_set_angles(waist=angle)
        await self.coordinator.async_request_refresh()
