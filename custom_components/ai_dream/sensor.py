"""Sensors for bed angles and the daily sleep report."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import AiDreamRuntimeData
from .const import AXES, CONF_ENABLE_WAIST, PROP_WAIST_ANGLE, Axis
from .coordinator import AiDreamCoordinator, AiDreamReportCoordinator
from .entity import AiDreamEntity, AiDreamReportEntity, supports_waist


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

    entities: list[SensorEntity] = []
    for axis in AXES:
        if axis.prop == PROP_WAIST_ANGLE and not waist:
            continue
        entities.append(AiDreamAngleSensor(coordinator, axis))

    for description in SLEEP_SENSORS:
        entities.append(AiDreamSleepSensor(runtime.report_coordinator, description))

    async_add_entities(entities)


class AiDreamAngleSensor(AiDreamEntity, SensorEntity):
    """Current angle reported by the bed."""

    _attr_native_unit_of_measurement = "°"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: AiDreamCoordinator, axis: Axis) -> None:
        super().__init__(coordinator, axis.key)
        self._axis = axis
        self._attr_translation_key = axis.key
        self._attr_icon = axis.icon

    @property
    def native_value(self) -> int | None:
        return (
            self.coordinator.data.angle(self._axis.prop)
            if self.coordinator.data
            else None
        )


@dataclass(frozen=True, kw_only=True)
class SleepSensorDescription:
    """Description of one value from the daily report."""

    key: str
    translation_key: str
    icon: str
    value_fn: Callable[[dict[str, Any]], Any]
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    attributes_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _nested(report: dict[str, Any], *path: str) -> Any:
    value: Any = report
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _sum_values(items: Any) -> int | float | None:
    if not isinstance(items, list):
        return None
    total: int | float = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        value = _number(item.get("value"))
        if value is not None:
            total += value
    return total


def _count_or_number(value: Any) -> int | float | None:
    if isinstance(value, list):
        return len(value)
    return _number(value)


def _timestamp(value: Any) -> datetime | None:
    try:
        return dt_util.utc_from_timestamp(float(value))
    except (TypeError, ValueError):
        return None


SLEEP_SENSORS: tuple[SleepSensorDescription, ...] = (
    SleepSensorDescription(
        key="sleep_score",
        translation_key="sleep_score",
        icon="mdi:star-circle-outline",
        value_fn=lambda report: _number(report.get("score")),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SleepSensorDescription(
        key="sleep_duration",
        translation_key="sleep_duration",
        icon="mdi:sleep",
        value_fn=lambda report: _number(report.get("sleepTime")),
        unit="min",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SleepSensorDescription(
        key="deep_sleep",
        translation_key="deep_sleep",
        icon="mdi:bed",
        value_fn=lambda report: _number(_nested(report, "deep", "value")),
        unit="min",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SleepSensorDescription(
        key="light_sleep",
        translation_key="light_sleep",
        icon="mdi:bed-outline",
        value_fn=lambda report: _number(_nested(report, "light", "value")),
        unit="min",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SleepSensorDescription(
        key="rem_sleep",
        translation_key="rem_sleep",
        icon="mdi:brain",
        value_fn=lambda report: _number(_nested(report, "rem", "value")),
        unit="min",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SleepSensorDescription(
        key="awake_time",
        translation_key="awake_time",
        icon="mdi:eye-outline",
        value_fn=lambda report: _number(_nested(report, "awake", "value")),
        unit="min",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SleepSensorDescription(
        key="heart_rate_avg",
        translation_key="heart_rate_avg",
        icon="mdi:heart-pulse",
        value_fn=lambda report: _number(report.get("heart_beat_avg")),
        unit="bpm",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SleepSensorDescription(
        key="breath_rate_avg",
        translation_key="breath_rate_avg",
        icon="mdi:lungs",
        value_fn=lambda report: _number(report.get("breath_avg")),
        unit="次/分",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SleepSensorDescription(
        key="body_moves",
        translation_key="body_moves",
        icon="mdi:rotate-3d-variant",
        value_fn=lambda report: _sum_values(report.get("body_move")),
        unit="次",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SleepSensorDescription(
        key="turn_overs",
        translation_key="turn_overs",
        icon="mdi:sync",
        value_fn=lambda report: _count_or_number(report.get("body_revolve")),
        unit="次",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SleepSensorDescription(
        key="snore_count",
        translation_key="snore_count",
        icon="mdi:sleep-off",
        value_fn=lambda report: _count_or_number(report.get("snore_count")),
        unit="次",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SleepSensorDescription(
        key="hrv_sdnn",
        translation_key="hrv_sdnn",
        icon="mdi:heart-flash",
        value_fn=lambda report: _number(_nested(report, "hrvResult", "daySdnn")),
        unit="ms",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SleepSensorDescription(
        key="hrv_stress",
        translation_key="hrv_stress",
        icon="mdi:emoticon-stressed-outline",
        value_fn=lambda report: _number(_nested(report, "hrvResult", "dayStress")),
        unit="%",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SleepSensorDescription(
        key="hrv_fatigue",
        translation_key="hrv_fatigue",
        icon="mdi:battery-heart-variant",
        value_fn=lambda report: _number(_nested(report, "hrvResult", "dayFatigued")),
        unit="%",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SleepSensorDescription(
        key="sleep_quality",
        translation_key="sleep_quality",
        icon="mdi:text-box-outline",
        value_fn=lambda report: report.get("sleepQualityTagValue"),
        attributes_fn=lambda report: {
            "advice": report.get("textTagValue"),
            "tags": report.get("tagKeys"),
        },
    ),
    SleepSensorDescription(
        key="sleep_start",
        translation_key="sleep_start",
        icon="mdi:clock-start",
        value_fn=lambda report: _timestamp(report.get("time_start")),
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SleepSensorDescription(
        key="sleep_end",
        translation_key="sleep_end",
        icon="mdi:clock-end",
        value_fn=lambda report: _timestamp(report.get("time_end")),
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
)


class AiDreamSleepSensor(AiDreamReportEntity, SensorEntity):
    """One value from today's sleep report."""

    def __init__(
        self,
        coordinator: AiDreamReportCoordinator,
        description: SleepSensorDescription,
    ) -> None:
        super().__init__(coordinator, f"report_{description.key}")
        self._description = description
        self._attr_translation_key = description.translation_key
        self._attr_icon = description.icon
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class

    @property
    def native_value(self) -> Any:
        if not self.coordinator.data:
            return None
        return self._description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data or not self._description.attributes_fn:
            return {}
        return self._description.attributes_fn(self.coordinator.data)
