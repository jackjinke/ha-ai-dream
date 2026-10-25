"""Shared entity helpers for AI Dream."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Device
from .const import DOMAIN
from .coordinator import AiDreamCoordinator, AiDreamReportCoordinator


def supports_waist(coordinator: AiDreamCoordinator, enabled: bool) -> bool:
    """Return whether a third (waist) motor should be exposed."""
    if enabled:
        return True
    state = coordinator.data
    if state and state.has_waist():
        return True
    return any(
        int(pattern.get("waistAngle") or 0) > 0
        for pattern in coordinator.device.patterns
        if isinstance(pattern, dict)
    )


class AiDreamEntity(CoordinatorEntity[AiDreamCoordinator]):
    """Base entity bound to a single bed."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AiDreamCoordinator, suffix: str) -> None:
        super().__init__(coordinator)
        self._device = coordinator.device
        self._attr_unique_id = f"{self._device.did}_{suffix}"
        self._attr_device_info = _device_info(self._device)


class AiDreamReportEntity(CoordinatorEntity[AiDreamReportCoordinator]):
    """Base entity for the slower sleep-report coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AiDreamReportCoordinator, suffix: str) -> None:
        super().__init__(coordinator)
        self._device = coordinator.device
        self._attr_unique_id = f"{self._device.did}_{suffix}"
        self._attr_device_info = _device_info(self._device)


def _device_info(device: Device) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, str(device.did))},
        manufacturer="AI Dream",
        model=device.product_code or "Smart bed",
        name=device.name,
    )
