#!/usr/bin/env python3
"""Probe the AI Dream cloud API against the real account/device.

Examples:
  python tools/probe.py --send-sms --phone 13800000000
  python tools/probe.py --phone 13800000000 --sms-code 123456
  python tools/probe.py --phone 13800000000 --password secret
  python tools/probe.py --token TOKEN --uid 1 --gid 1

The script only reads data unless --move-test is given.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import types
from datetime import date
from pathlib import Path

import aiohttp


def _load_client() -> types.ModuleType:
    """Load the pure API modules without executing the HA integration package."""
    root = Path(__file__).resolve().parents[1] / "custom_components" / "ai_dream"
    package_name = "_aidream_client"
    package = types.ModuleType(package_name)
    package.__path__ = [str(root)]
    sys.modules[package_name] = package

    for module_name in ("const", "api"):
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.{module_name}", root / f"{module_name}.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot load {module_name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{package_name}.api"]


_client = _load_client()
AiDreamApi = _client.AiDreamApi
AiDreamError = _client.AiDreamError


def dump(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


async def run(args: argparse.Namespace) -> None:
    async with aiohttp.ClientSession() as session:
        api = AiDreamApi(session)

        if args.from_file:
            saved = json.loads(Path(args.from_file).read_text())
            api.restore_auth(saved["token"], saved["uid"], saved.get("gid"))
            print(f"Loaded session: uid={api.uid} gid={api.gid}")
        elif args.token:
            api.restore_auth(args.token, args.uid or 0, args.gid)
        elif args.send_sms:
            if not args.phone:
                raise SystemExit("--phone is required with --send-sms")
            await api.send_sms_code(args.phone)
            print("SMS requested. Re-run with --sms-code <code>.")
            return
        elif args.sms_code:
            await api.login_sms(args.phone, args.sms_code)
            print(f"Login OK: uid={api.uid} gid={api.gid}")
        elif args.password:
            await api.login_password(args.phone, args.password)
            print(f"Login OK: uid={api.uid} gid={api.gid}")
        else:
            raise SystemExit(
                "Provide --token, --sms-code or --password (or --send-sms)"
            )

        if args.save:
            path = Path(args.save)
            path.write_text(
                json.dumps({"token": api.token, "uid": api.uid, "gid": api.gid})
            )
            path.chmod(0o600)
            print(f"Session saved to {path}")

        devices = await api.get_devices()
        print(f"\nDevices ({len(devices)}):")
        for device in devices:
            print(
                f"  did={device.did} name={device.name!r} mac={device.mac} "
                f"product={device.product_code} online={device.online} "
                f"patterns={len(device.patterns)}"
            )

        target = devices[0] if args.did is None and devices else None
        if args.did is not None:
            target = next((d for d in devices if d.did == args.did), None)
        if target is None:
            return

        print(f"\nPatterns for did={target.did}:")
        dump(target.patterns)

        state = await api.get_device_state(target.did)
        print(f"\nState for did={target.did} ({len(state)} properties):")
        dump(state)

        if args.report:
            day = args.day or date.today().isoformat()  # noqa: DTZ011
            report = await api.get_day_report(target.did, day)
            print(f"\nReport for {day}:")
            dump(report)

        if args.move_test:
            if not args.i_understand:
                raise SystemExit("--move-test requires --i-understand")
            print("\nMoving head to 2 degrees ...")
            await api.set_angles(
                target.did,
                head=2,
                waist=int(float(state.get("WaistAngle") or 0)),
                leg=int(float(state.get("LegAngle") or 0)),
            )
            print("Command accepted. Restore the bed in the app when finished.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phone", default=os.environ.get("AIDREAM_PHONE"))
    parser.add_argument("--password", default=os.environ.get("AIDREAM_PASSWORD"))
    parser.add_argument("--sms-code", default=os.environ.get("AIDREAM_SMS_CODE"))
    parser.add_argument("--send-sms", action="store_true")
    parser.add_argument("--from-file")
    parser.add_argument("--save")
    parser.add_argument("--token", default=os.environ.get("AIDREAM_TOKEN"))
    parser.add_argument("--uid", type=int, default=os.environ.get("AIDREAM_UID"))
    parser.add_argument("--gid", type=int, default=os.environ.get("AIDREAM_GID"))
    parser.add_argument("--did", type=int)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--day", help="report date, YYYY-MM-DD (default: today)")
    parser.add_argument("--move-test", action="store_true")
    parser.add_argument("--i-understand", action="store_true")
    args = parser.parse_args()

    try:
        asyncio.run(run(args))
    except AiDreamError as err:
        raise SystemExit(f"API error: {err}") from err


if __name__ == "__main__":
    main()
