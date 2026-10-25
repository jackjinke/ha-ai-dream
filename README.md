# AI Dream for Home Assistant

Unofficial Home Assistant custom integration (`custom_components/ai_dream`) for smart beds controlled through the **AI Dream** mobile app (`com.aidream.ispring`), including Serta China's **舒达 ICF AI Max 智能底床**.

## Status and evidence

This integration is open-source software built by analyzing `com.aidream.ispring` 2.10.1 and verified live against a **舒达 ICF AI Max 智能底床** (product code `E1SD`, single bed, no waist motor). It is published as a **HACS custom repository** at [jackjinke/ha-ai-dream](https://github.com/jackjinke/ha-ai-dream); it is not in the HACS default store. Licensed under the MIT License.

**Verified live against `https://appapi.aidream.website` and an `E1SD` bed:**

- SMS verification-code login and device discovery (`online=1`, 3 saved presets)
- Property snapshot polling (22 properties, including `HeadAngle`, `LegAngle`, `WaistAngle`, `OnBed`, `NightLight`, `ChildLock`, and `FunctionSupport`)
- Absolute angle control (`HeadAngle` moved `0° → 2°`; `HeadState.TargetAngle=2` appeared immediately and `HeadAngle=2` followed within ~4 s)
- Preset recall (`一键放平` with `modeCtrl=1` restored head and leg to `0°` and reported `ModeStatus.ModeCtrl=1`)
- Under-bed light switch (`NightLight` toggled `000000000100` → `100000000100` → restored to `000000000100`)
- Daily sleep report (`getday`): sleep score, duration, stage breakdown, average heart and breathing rates, body movements, turn-overs, and HRV metrics

**Implemented from APK analysis, but not live-verified:**

- **Password login**: the server accepted the AES-256-ECB ciphertext format and returned business code `1300` on an intentional wrong-password check, but end-to-end login with a real account password was not executed
- **Child lock switch**: snapshot state (`ChildLock="0"`) was read from the bed, but write commands were not toggled on the live bed
- **Massage preset passthrough**: forwarding `patternDetails` (`identifier="Massage"`) during preset recall
- **Waist motor axis**: the tested `E1SD` has no waist motor (`WaistAngleMax=0`)
- **Split-bed prefixes**: parsing `SideA:` and `SideB:` snapshot keys (only a single bed was tested)

Only a subset of these paths is indirectly exercised by the automated test suite (such as forced waist entity creation, report/setup relogin, and pending-target merging); password login, `ChildLock` writes, `Massage` passthrough, and `SideA:`/`SideB:` prefixes do not have live-device or dedicated write tests.
See [`docs/verification.md`](docs/verification.md) for measured test data and [`docs/protocol.md`](docs/protocol.md) for reverse-engineered cloud API details.

## How it works

The integration uses `iot_class: "cloud_polling"` and `integration_type: "device"` (one config entry per bed).

Even when the AI Dream app controls an ICF bed over Wi-Fi, the bed communicates with `https://appapi.aidream.website` and the app talks to that cloud service. Home Assistant only needs outbound HTTPS access to `appapi.aidream.website`:

- Home Assistant does **not** need to be on the same LAN or VLAN as the bed.
- Bluetooth (BLE) is **not** required. (Local HTTP `/api/...` endpoints present in the APK belong to a different air-mattress product family, not ICF beds.)
- Bed state snapshots are polled every **30 seconds** by default; the daily sleep report is polled every **30 minutes**.

## Installation

### HACS (recommended)

This repository is a HACS **custom repository**, not a default-store integration.
You need [HACS](https://hacs.xyz/) installed in Home Assistant.

1. Open **HACS → Integrations**.
2. Open the three-dot menu → **Custom repositories**.
3. Add `https://github.com/jackjinke/ha-ai-dream` with category **Integration**.
4. Search for **AI Dream** in HACS, open it, and click **Download**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration → AI Dream**.
7. Enter the phone number registered with the AI Dream app and choose **SMS verification code** or **Password**.
8. If the account has multiple beds, select the bed to add.

### Manual

1. Copy `custom_components/ai_dream` into `<config>/custom_components/ai_dream` on your Home Assistant instance.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → AI Dream**.
4. Enter the phone number registered with the AI Dream app and choose **SMS verification code** or **Password**.
5. If the account has multiple beds, select the bed to add.

## Options

Configure per-entry options under **Settings → Devices & services → AI Dream → Configure**:

| Option | Key | Default | Description |
| --- | --- | --- | --- |
| **Polling interval** | `scan_interval` | `30` s | Bed snapshot polling interval (`10`–`600` seconds, step `5` s). |
| **Enable the waist motor** | `enable_waist` | `false` | Force-enable waist entities for beds whose third motor is not auto-detected from `FunctionSupport.WaistAngleMax`, `WaistAngle`, or preset definitions. This is a software override and does not add hardware: enabling it on a two-motor bed like `E1SD` creates waist entities with a fallback `8°` limit, but the bed may ignore waist commands. |

## Entities

Entity IDs are derived from the bed name; the table below lists the default English object ID suffixes from `translations/en.json`.

| Entity | Friendly name | Description |
| --- | --- | --- |
| `cover.*_head_angle` | **Head angle** | Maps `0–100%` to `0–HeadAngleMax` (`60°` on `E1SD`). Exposes `angle`, `max_angle`, and `target_angle` attributes. |
| `cover.*_leg_angle` | **Leg angle** | Maps `0–100%` to `0–LegAngleMax` (`45°` on `E1SD`). |
| `cover.*_waist_angle` | **Waist angle** | Optional. Created only when a waist motor is auto-detected or forced via **Enable the waist motor** (fallback `8°` max). |
| `number.*_head_target_angle` | **Head target angle** | Exact head target angle in degrees (`0–HeadAngleMax`, step `1°`). |
| `number.*_leg_target_angle` | **Leg target angle** | Exact leg target angle in degrees (`0–LegAngleMax`, step `1°`). |
| `number.*_waist_target_angle` | **Waist target angle** | Optional. Exact waist target angle in degrees (`0–WaistAngleMax` or `0–8°` when forced). |
| `sensor.*_head_angle` | **Head angle** | Current reported head angle (`°`). |
| `sensor.*_leg_angle` | **Leg angle** | Current reported leg angle (`°`). |
| `sensor.*_waist_angle` | **Waist angle** | Optional. Current reported waist angle (`°`). |
| `sensor.*_sleep_score` | **Sleep score** | Daily sleep score. |
| `sensor.*_sleep_duration` | **Sleep duration** | Total sleep time (`min`). |
| `sensor.*_deep_sleep`, `*_light_sleep`, `*_rem_sleep`, `*_awake_time` | **Deep sleep**, **Light sleep**, **REM sleep**, **Awake time** | Sleep stage durations (`min`). |
| `sensor.*_average_heart_rate` | **Average heart rate** | Overnight average heart rate (`bpm`). |
| `sensor.*_average_breathing_rate` | **Average breathing rate** | Overnight average breathing rate (`次/分`). |
| `sensor.*_body_movements` | **Body movements** | Sum of `body_move` counts across the sleep session (`次`). |
| `sensor.*_turn_overs` | **Turn-overs** | Count of `body_revolve` events (`次`). |
| `sensor.*_snore_events` | **Snore events** | Count of `snore_count` entries (`次`). |
| `sensor.*_hrv_sdnn` | **HRV SDNN** | Daily HRV SDNN (`ms`). |
| `sensor.*_stress_index`, `*_fatigue_index` | **Stress index**, **Fatigue index** | HRV-derived daily stress and fatigue indices (`%`). |
| `sensor.*_sleep_quality` | **Sleep quality** | Summary tag; exposes `advice` and `tags` in state attributes. |
| `sensor.*_fell_asleep`, `*_woke_up` | **Fell asleep**, **Woke up** | Sleep start and end timestamps (UTC). |
| `binary_sensor.*_on_bed` | **On bed** | Occupancy state reported by `OnBed`. |
| `binary_sensor.*_cloud_connection` | **Cloud connection** | Diagnostic connectivity sensor; stays available and reports `off` when cloud polling fails. |
| `switch.*_under_bed_light` | **Under-bed light** | Toggles the enable flag of the `NightLight` program while preserving schedule and brightness digits. |
| `switch.*_child_lock` | **Child lock** | Toggles `ChildLock` (`0`/`1`; write path unverified on live hardware). |
| `button.*` | *(Preset name)* | One button per saved preset/mode on the account (for example `一键放平`, `零压模式`). |

## Sleep report

The report coordinator queries `POST /ammsreport/app/report/did/getday` every 30 minutes for the current local date (`YYYY-MM-DD`).

- Reports are generated by the AI Dream cloud after a sleep session ends, not streamed in real time.
- Before a report is available for the current date, the endpoint returns `data: null` and sleep report sensors remain `unknown`.
- There is no live heart-rate or breathing-rate telemetry stream in the cloud snapshot.

## Limitations and security

- **Private cloud dependency**: the integration relies on an undocumented vendor API (`appapi.aidream.website`) that can change without notice.
- **Token lifetime and credential storage**: cloud tokens expire after roughly 15 days (`code="1100"`).
  - **Password login** stores your password in Home Assistant's config entry storage (`.storage/core.config_entries`) so the coordinator can renew expired tokens automatically. Note that password login has not been verified end-to-end with a real account.
  - **SMS login** does not store a password; when the token expires, Home Assistant raises a re-authentication repair flow prompting for a new SMS code.
- **Single active session**: logging in from multiple clients with the same AI Dream account may invalidate older tokens.
- **Under-bed light**: Home Assistant only flips the leading on/off digit of the `NightLight` program string; schedule windows and brightness levels must be configured in the AI Dream app.

## Development and tests

Run the automated test suite (`pytest-homeassistant-custom-component 0.13.374` / Home Assistant `2026.10.3`, 12 tests in `tests/test_integration.py`):

```bash
python3 -m venv .venv-test && .venv-test/bin/pip install -r requirements_test.txt && .venv-test/bin/python -m pytest -q
```

A standalone CLI probe (`tools/probe.py`) loads `const.py` and `api.py` directly without Home Assistant and only requires `tools/requirements.txt` (`aiohttp`, `cryptography`). See [`docs/verification.md`](docs/verification.md) for probe commands and live test results.

## Disclaimer

This project is an independent, unofficial integration and is not affiliated with, endorsed by, or supported by 爱梦睡眠（珠海）智能科技有限公司 (AI Dream) or Serta (舒达). Moving a motorized bed remotely can cause injury or property damage; keep the bed clear of people, pets, and obstructions before running tests or automations.
