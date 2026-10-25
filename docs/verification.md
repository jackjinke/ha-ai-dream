# Verification notes

- **Date**: 2026-10-25
- **Hardware**: Serta China **舒达 ICF AI Max 智能底床**, product code `E1SD` (single bed, no waist motor)
- **Cloud endpoint**: `https://appapi.aidream.website`
- **Reference app**: AI Dream `2.10.1` (`com.aidream.ispring`), decompiled with `jadx 1.5.6`

All account and device identifiers (`phone`, `token`, `uid`, `gid`, `did`, `mac`) are redacted in this document. See [`docs/protocol.md`](protocol.md) for endpoint payloads and [`README.md`](../README.md) for integration usage.

## Live cloud and hardware evidence

The following operations were executed against `https://appapi.aidream.website` and the physical `E1SD` bed with the owner's consent:

| Step | Endpoint | Measured result |
| --- | --- | --- |
| Request and complete SMS login | `POST /amcustomer/app/sms/sendcodenotlogin`, `POST /amcustomer/app/userinfo/phone/login` | `code="1000"`, returned `token`, `uid`, `gid` (redacted) |
| Password ciphertext probe | `POST /amcustomer/app/userinfo/login/ciphertext` | Server accepted AES-256-ECB ciphertext format and returned `code="1300"` on an intentional wrong-password check; full login with a real password was **not** executed |
| Device discovery | `GET /amdevice/app/device/gethomepage?gid=<gid>` | 1 bed (`did` redacted), `productCode="E1SD"`, `online=1`, 3 presets in `patterns` |
| Property snapshot | `GET /amelectricbed/app/propertysnapshot/getlocallist/<did>` | 22 properties; `HeadAngle="0"`, `LegAngle="0"`, `WaistAngle="0"`, `OnBed="1"`, `ChildLock="0"`, `NightLight="000000000100"` |
| Axis limits | `FunctionSupport` in snapshot | `HeadAngleMax=60`, `LegAngleMax=45`, `WaistAngleMax=0` |
| Move head `0° → 2°` | `POST /amelectricbed/app/thingprop/angleset/<did>` | `HeadState.TargetAngle=2` appeared immediately; `HeadAngle="2"` reached within ~4 s |
| Recall `一键放平` (`modeCtrl=1`) | `POST /amelectricbed/app/thingprop/angleset/<did>` | Head and leg returned to `0°`; `ModeStatus.ModeCtrl=1` |
| Toggle under-bed light | `POST /amelectricbed/app/thingprop/<did>` | `NightLight` changed `000000000100` → `100000000100` → restored to `000000000100` |
| Daily sleep report | `POST /ammsreport/app/report/did/getday` | `score=95`, `sleepTime=570` min (`deep=391`, `light=29`, `rem=150`, `awake=0`), `heart_beat_avg=63` bpm, `breath_avg=13`, `body_move` sum `255`, `body_revolve` count `9` (turn-overs), `hrvResult`: `daySdnn=60`, `dayStress=28`, `dayFatigued=53` |

**Final bed state after live testing:** flat (`HeadAngle=0`, `LegAngle=0`, `ModeStatus.ModeCtrl=1`), under-bed light off (`000000000100`), child lock off (`ChildLock=0`).

### Features implemented but not exercised on the live bed

- Completing password login with valid account credentials (only ciphertext format acceptance and `1300` rejection were verified against the server)
- Toggling `ChildLock` on the live bed (only snapshot read `ChildLock="0"` was verified)
- Preset `Massage` (`patternDetails`) property passthrough
- Waist motor movement (`E1SD` reports `WaistAngleMax=0` and has no waist actuator)
- Split-bed `SideA:` / `SideB:` property prefixes (only single-bed `E1SD` hardware was tested)

## Home Assistant and test suite verification

Verification was performed in two environments:

1. **Home Assistant `2026.10.4` import and static check**:
   - All modules under `custom_components/ai_dream` and `tools/probe.py` were imported against Home Assistant `2026.10.4` and checked with `ruff`.
2. **Automated integration test harness (`pytest-homeassistant-custom-component 0.13.374` / Home Assistant `2026.10.3`)**:
   - 12 tests in `tests/test_integration.py` passed against a mocked cloud API:
     - `test_setup_and_control`: config entry setup, entity registration across all platforms, `cover.set_cover_position(50)` (`head=30`, `leg=22`), `number.set_value(15)` (`head=15`), sleep score sensor (`95`), and reload behavior (options change reloads the entry; token update does not reload)
     - `test_pending_targets_merge`: back-to-back axis commands preserve in-flight target angles before the next snapshot arrives
     - `test_expired_pending_refreshes_before_sending`: when a pending target expires, the coordinator refreshes and publishes a snapshot before composing a full angle command; a following command still uses the refreshed angle instead of the old cache
     - `test_explicit_target_survives_pre_send_snapshot`: an in-flight snapshot started before an angle command is sent cannot confirm or clear the newly requested target angle
     - `test_forced_waist_has_positive_limit`: enabling `enable_waist` on an `E1SD` snapshot exposes `cover.*_waist_angle` with `max_angle=8`
     - `test_cloud_connection_stays_readable`: `binary_sensor.*_cloud_connection` stays available and reports `off` when `last_update_success` is `False`
     - `test_relogin_error_classification`: transport timeouts raise `UpdateFailed`, credential rejection (`code="1300"`) returns `False` so re-authentication can be triggered, and a late response carrying an old token skips relogin when a newer token is already present
     - `test_config_flow`: phone → SMS verification step → config entry creation
     - `test_device_metadata_after_relogin`: expired token during initial `get_devices` refreshes via stored password and registers preset buttons
     - `test_report_relogin`: when `getday` returns `1100` (expired token), the report coordinator re-authenticates with the stored password and retries fetching the daily report
     - `test_setup_retry_on_relogin_transport_error`: a transport error or timeout during startup relogin transitions the config entry to `SETUP_RETRY` rather than failing authentication
     - `test_device_list_still_rejected_starts_reauth`: if the device list still returns `1100` after a successful relogin, setup starts the reauthentication flow instead of retrying forever

## Reproduce

### Automated tests

```bash
python3 -m venv .venv-test && .venv-test/bin/pip install -r requirements_test.txt && .venv-test/bin/python -m pytest -q
```

### Standalone live API probe

`tools/probe.py` loads `const.py` and `api.py` directly without importing Home Assistant, so it only needs `tools/requirements.txt` (`aiohttp` and `cryptography`):

```bash
python3 -m venv .venv
.venv/bin/pip install -r tools/requirements.txt

# 1. Request an SMS login code
.venv/bin/python tools/probe.py --send-sms --phone <phone>

# 2. Log in with the SMS code and save the session locally (mode 0600)
.venv/bin/python tools/probe.py --phone <phone> --sms-code <code> --save .secrets.json

# 3. Read device list, patterns, snapshot, and a daily sleep report
.venv/bin/python tools/probe.py --from-file .secrets.json --report --day 2026-10-25
```

To test physical movement, pass `--move-test --i-understand`. This moves the head section to `2°` and does **not** automatically return the bed to `0°`; run it only when the bed is clear and restore the position in the AI Dream app afterwards.
