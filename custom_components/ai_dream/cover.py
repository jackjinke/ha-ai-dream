"""Covers that expose the bed's motorised angles."""

from __future__ import annotations

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverEntity,
    CoverEntityFeature,
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
    enable_waist = bool(entry.options.get(CONF_ENABLE_WAIST, False))
    waist = supports_waist(coordinator, enable_waist)

    entities: list[AiDreamCover] = []
    for axis in AXES:
        if axis.prop == PROP_WAIST_ANGLE and not waist:
            continue
        entities.append(AiDreamCover(coordinator, axis))
    async_add_entities(entities)


class AiDreamCover(AiDreamEntity, CoverEntity):
    """A single motorised axis of the bed."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, coordinator: AiDreamCoordinator, axis: Axis) -> None:
        super().__init__(coordinator, axis.key)
        self._axis = axis
        self._attr_translation_key = axis.key
        self._attr_icon = axis.icon

    @property
    def _angle(self) -> int | None:
        return (
            self.coordinator.data.angle(self._axis.prop)
            if self.coordinator.data
            else None
        )

    @property
    def _max_angle(self) -> int:
        if self.coordinator.data:
            reported = self.coordinator.data.max_angle(self._axis.prop)
            if reported > 0:
                return reported
        return self._axis.max_angle

    @property
    def current_cover_position(self) -> int | None:
        angle = self._angle
        if angle is None:
            return None
        return max(0, min(100, round(angle * 100 / self._max_angle)))

    @property
    def is_closed(self) -> bool | None:
        angle = self._angle
        return None if angle is None else angle <= 0

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        attrs = {"max_angle": self._max_angle}
        if self._angle is not None:
            attrs["angle"] = self._angle
        target = self._target_angle
        if target is not None:
            attrs["target_angle"] = target
        return attrs

    @property
    def _target_angle(self) -> int | None:
        state = self.coordinator.data
        if not state:
            return None
        payload = state.raw.get(self._axis.state_key)
        if not isinstance(payload, dict):
            return None
        try:
            return int(payload.get("TargetAngle"))
        except (TypeError, ValueError):
            return None

    async def async_set_cover_position(self, **kwargs) -> None:
        position = kwargs[ATTR_POSITION]
        await self._async_move(round(position * self._max_angle / 100))

    async def async_open_cover(self, **kwargs) -> None:
        await self._async_move(self._max_angle)

    async def async_close_cover(self, **kwargs) -> None:
        await self._async_move(0)

    async def _async_move(self, angle: int) -> None:
        angle = max(0, min(self._max_angle, int(angle)))
        if self._axis.prop == PROP_HEAD_ANGLE:
            await self.coordinator.async_set_angles(head=angle)
        elif self._axis.prop == PROP_LEG_ANGLE:
            await self.coordinator.async_set_angles(leg=angle)
        else:
            await self.coordinator.async_set_angles(waist=angle)
        await self.coordinator.async_request_refresh()
