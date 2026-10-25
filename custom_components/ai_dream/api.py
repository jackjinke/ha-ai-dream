"""Async client for the AI Dream cloud API.

The endpoints and payloads mirror the Android application
``com.aidream.ispring`` (2.10.1).  The bed talks to the AI Dream cloud over
Wi-Fi, so this client works without any local network path to the bed.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import (
    BASE_URL,
    PASSWORD_KEY,
    PATH_ALL_STATE,
    PATH_ANGLESET,
    PATH_DAY_REPORT,
    PATH_DEVICES,
    PATH_LOGIN_PASSWORD,
    PATH_LOGIN_SMS,
    PATH_SMS_CODE,
    PATH_THINGPROP,
    REQUEST_TIMEOUT,
    SMS_TYPE_LOGIN,
)

_LOGGER = logging.getLogger(__name__)

SUCCESS_CODE = "1000"
TOKEN_INVALID_CODE = "1100"


class AiDreamError(Exception):
    """Base error for the AI Dream API."""


class AiDreamAuthError(AiDreamError):
    """The token is missing or expired."""


class AiDreamApiError(AiDreamError):
    """The API returned a business error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class Device:
    """A bed bound to the account."""

    did: int
    name: str
    mac: str | None = None
    product_code: str | None = None
    online: bool = False
    patterns: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def encrypt_password(password: str) -> str:
    """Replicate the client-side password encryption."""
    key = hashlib.sha256(PASSWORD_KEY.encode("utf-8")).digest()
    padder = padding.PKCS7(128).padder()
    padded = padder.update(password.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()


class AiDreamApi:
    """Thin async wrapper around the AI Dream HTTP API."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self.token: str | None = None
        self.uid: int | None = None
        self.gid: int | None = None
        self.auth_lock = asyncio.Lock()

    def restore_auth(self, token: str, uid: int, gid: int | None) -> None:
        self.token = token
        self.uid = uid
        self.gid = gid

    @property
    def _auth_headers(self) -> dict[str, str]:
        if not self.token:
            raise AiDreamAuthError("No token available")
        return {
            "token": self.token,
            "caller_uid": str(self.uid or 0),
            "Authorization": self.token,
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if auth:
            headers.update(self._auth_headers)

        url = f"{BASE_URL}{path}"
        try:
            async with self._session.request(
                method,
                url,
                json=body,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                text = await response.text()
                if response.status != 200:
                    raise AiDreamApiError(
                        str(response.status), f"HTTP {response.status}: {text[:200]}"
                    )
                try:
                    payload = json.loads(text)
                except ValueError as err:
                    raise AiDreamApiError("-1", f"Invalid JSON: {text[:200]}") from err
        except aiohttp.ClientError as err:
            raise AiDreamApiError("-1", f"Connection error: {err}") from err
        except TimeoutError as err:
            raise AiDreamApiError("-1", "Request timed out") from err

        if not isinstance(payload, dict):
            raise AiDreamApiError("-1", "Unexpected response shape")

        code = str(payload.get("code", ""))
        if code == SUCCESS_CODE:
            return payload.get("data")
        if code == TOKEN_INVALID_CODE:
            raise AiDreamAuthError(payload.get("msg") or "Authentication failed")
        raise AiDreamApiError(code, payload.get("msg") or "Unknown error")

    async def send_sms_code(self, phone: str) -> None:
        """Ask the service to send a login SMS."""
        await self._request(
            "POST",
            PATH_SMS_CODE,
            body={"mobile": phone, "smsType": SMS_TYPE_LOGIN},
            auth=False,
        )

    async def login_sms(self, phone: str, code: str) -> None:
        data = await self._request(
            "POST",
            PATH_LOGIN_SMS,
            body={
                "mobile": phone,
                "smsCode": code,
                "appVersion": "2.10.1",
                "phoneModel": "Home Assistant",
                "phoneSysVersion": "1",
            },
            auth=False,
        )
        self._apply_login(data)

    async def login_password(self, phone: str, password: str) -> None:
        data = await self._request(
            "POST",
            PATH_LOGIN_PASSWORD,
            body={
                "mobile": phone,
                "psword": encrypt_password(password),
                "appVersion": "2.10.1",
                "phoneModel": "Home Assistant",
                "phoneSysVersion": "1",
            },
            auth=False,
        )
        self._apply_login(data)

    def _apply_login(self, data: Any) -> None:
        if not isinstance(data, dict) or not data.get("token"):
            raise AiDreamApiError("-1", "Login response has no token")
        self.token = str(data["token"])
        self.uid = int(data.get("uid") or 0)
        self.gid = int(data["gid"]) if data.get("gid") is not None else None

    async def get_devices(self) -> list[Device]:
        if not self.gid:
            raise AiDreamApiError("-1", "Home id is not known")
        data = await self._request("GET", PATH_DEVICES, params={"gid": self.gid})
        if not isinstance(data, dict):
            return []
        devices: list[Device] = []
        for item in data.get("hpDeviceDtoList") or []:
            if not isinstance(item, dict):
                continue
            devices.append(
                Device(
                    did=int(item.get("did") or 0),
                    name=str(
                        item.get("nickName") or item.get("groupName") or "AI Dream Bed"
                    ),
                    mac=item.get("mac"),
                    product_code=item.get("productCode"),
                    online=str(item.get("online", "")).lower() in ("1", "true", "on"),
                    patterns=[
                        pattern
                        for pattern in (item.get("patterns") or [])
                        if isinstance(pattern, dict)
                    ],
                    raw=item,
                )
            )
        return devices

    async def get_device_state(self, did: int) -> dict[str, Any]:
        """Return the local property snapshot as ``identifier -> parsed value``."""
        data = await self._request("GET", PATH_ALL_STATE.format(did=did))
        result: dict[str, Any] = {}
        for item in data or []:
            if not isinstance(item, dict):
                continue
            identifier = item.get("identifier")
            if not identifier:
                continue
            value = item.get("dataValue")
            result[identifier] = _parse_value(value)
        return result

    async def set_angles(
        self,
        did: int,
        *,
        head: int,
        leg: int,
        waist: int = 0,
        mode_ctrl: int = 0,
    ) -> None:
        """Move the bed to absolute angles (degrees)."""
        await self._request(
            "POST",
            PATH_ANGLESET.format(did=did),
            body={
                "headAngle": head,
                "waistAngle": waist,
                "legAngle": leg,
                "modeCtrl": mode_ctrl,
            },
        )

    async def set_property(self, did: int, key: str, value: Any) -> None:
        await self._request(
            "POST",
            PATH_THINGPROP.format(did=did),
            body={"prop": {key: value}},
        )

    async def get_day_report(self, did: int, day: str) -> dict[str, Any] | None:
        """Return the sleep report for a local calendar day (YYYY-MM-DD)."""
        data = await self._request(
            "POST", PATH_DAY_REPORT, body={"did": did, "day": day}
        )
        return data if isinstance(data, dict) else None


def _parse_value(value: Any) -> Any:
    """Snapshot values are strings; only object/array values are JSON.

    Plain numbers are intentionally kept as strings: some properties (night
    light schedules) are zero-padded digit strings whose leading zeros carry
    meaning.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    if text[0] in "[{":
        try:
            return json.loads(text)
        except ValueError:
            return text
    return text
