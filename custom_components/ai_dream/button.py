"""Buttons for the bed's saved positions and modes."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AiDreamRuntimeData
from .const import PROP_HEAD_ANGLE, PROP_LEG_ANGLE, PROP_WAIST_ANGLE
from .coordinator import AiDreamCoordinator
from .entity import AiDreamEntity

_PATTERN_NAME_FALLBACKS = {
    "model_lyflat": "一键放平",
    "model_zeropress": "零压模式",
    "model_music": "音乐模式",
    "model_movie": "影院模式",
    "model_comfort": "舒适模式",
    "model_lactation": "哺乳模式",
    "model_morning": "唤醒模式",
    "model_nurse": "护理模式",
    "model_office": "办公模式",
    "model_phone": "阅读模式",
    "model_play": "娱乐模式",
    "model_relax": "放松模式",
    "model_rest": "休息模式",
    "model_sleep": "睡眠模式",
    "model_sleephelp": "助眠模式",
    "model_think": "思考模式",
    "model_yoga": "瑜伽模式",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: AiDreamRuntimeData = entry.runtime_data
    coordinator = runtime.coordinator
    patterns = runtime.device.patterns

    used_names: dict[str, int] = {}
    entities: list[AiDreamPresetButton] = []
    for index, pattern in enumerate(patterns):
        name = _pattern_name(pattern, index)
        count = used_names.get(name, 0) + 1
        used_names[name] = count
        if count > 1:
            name = f"{name} {count}"
        entities.append(AiDreamPresetButton(coordinator, pattern, name, index))
    async_add_entities(entities)


def _pattern_name(pattern: dict[str, Any], index: int) -> str:
    for key in ("patternName", "titleName", "modelName", "name"):
        value = pattern.get(key)
        if isinstance(value, str) and value:
            return _PATTERN_NAME_FALLBACKS.get(value, value)
    return f"预设 {index + 1}"


class AiDreamPresetButton(AiDreamEntity, ButtonEntity):
    """Recall one saved bed position or mode."""

    def __init__(
        self,
        coordinator: AiDreamCoordinator,
        pattern: dict[str, Any],
        name: str,
        index: int,
    ) -> None:
        pattern_id = pattern.get("patternId") or pattern.get("id")
        suffix = f"preset_{pattern_id}" if pattern_id else f"preset_index_{index}"
        super().__init__(coordinator, suffix)
        self._pattern = pattern
        self._attr_name = name
        self._attr_icon = "mdi:bed"

    async def async_press(self) -> None:
        state = self.coordinator.data
        pattern = self._pattern

        def angle(prop: str, key: str) -> int:
            value = pattern.get(key)
            if value is None and state is not None:
                value = state.angle(prop)
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        await self.coordinator.async_set_angles(
            head=angle(PROP_HEAD_ANGLE, "headAngle"),
            leg=angle(PROP_LEG_ANGLE, "legAngle"),
            waist=angle(PROP_WAIST_ANGLE, "waistAngle"),
            mode_ctrl=_as_int(pattern.get("modeCtrl")) or 0,
        )

        for detail in pattern.get("patternDetails") or []:
            if not isinstance(detail, dict) or detail.get("identifier") != "Massage":
                continue
            try:
                massage = json.loads(detail.get("dataValue") or "{}")
            except ValueError:
                continue
            if isinstance(massage, dict):
                await self.coordinator.async_set_property("Massage", massage)

        await self.coordinator.async_request_refresh()


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
