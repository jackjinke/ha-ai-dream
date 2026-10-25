"""Binary sensors for occupancy and connectivity."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AiDreamRuntimeData
from .coordinator import AiDreamCoordinator
from .entity import AiDreamEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime: AiDreamRuntimeData = entry.runtime_data
    coordinator = runtime.coordinator
    entities: list[BinarySensorEntity] = [AiDreamConnectivitySensor(coordinator)]
    if coordinator.data and coordinator.data.on_bed is not None:
        entities.append(AiDreamOnBedSensor(coordinator))
    async_add_entities(entities)


class AiDreamConnectivitySensor(AiDreamEntity, BinarySensorEntity):
    """Whether the cloud can currently read the bed."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "online"

    def __init__(self, coordinator: AiDreamCoordinator) -> None:
        super().__init__(coordinator, "online")

    @property
    def available(self) -> bool:
        """Keep the diagnostic readable so automations can see ``off``."""
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class AiDreamOnBedSensor(AiDreamEntity, BinarySensorEntity):
    """Presence sensor reported by the bed."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_translation_key = "on_bed"

    def __init__(self, coordinator: AiDreamCoordinator) -> None:
        super().__init__(coordinator, "on_bed")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.on_bed if self.coordinator.data else None
