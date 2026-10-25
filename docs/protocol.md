# AI Dream cloud protocol

Reverse-engineering notes from `com.aidream.ispring` 2.10.1 (`classes.dex`, `lib_network`, `feature_bleprotocol`, `lib_mqttclient`), verified against `https://appapi.aidream.website` and a Serta China **舒达 ICF AI Max 智能底床** (`productCode="E1SD"`, single bed, no waist motor).

When the mobile app controls an ICF bed over Wi-Fi, the bed is connected to the AI Dream cloud and the app communicates with that cloud over HTTPS/WebSocket. Each section below marks whether behavior was **verified live** on `E1SD` or **inferred from APK decompilation**.

See [`docs/verification.md`](verification.md) for measured responses and [`README.md`](../README.md) for Home Assistant entity mapping.

## Base URL and service prefixes

```text
https://appapi.aidream.website
```

The first path segment routes to a backend service:

| Prefix | Purpose | Verification status |
| --- | --- | --- |
| `amcustomer` | Account management, SMS codes, login | Verified live |
| `amdevice` | Home groups and device discovery | Verified live |
| `amelectricbed` | Bed property snapshots and control commands | Verified live |
| `ammsreport` | Daily and monthly sleep reports | `getday` verified live; `latest` reachable (`data: null`); `getmonth` inferred from APK and parameter validation |
| `ammessage` | Push/MQTT access credentials | Seen in APK; not used |
| `amnettypush` | WebSocket push token | Seen in APK; not used |

## Authentication headers and response envelope

Authenticated requests include three headers—`token` and `Authorization` carry the session token, while `caller_uid` carries the numeric user ID (`uid`) as a decimal string:

```http
token: <token>
caller_uid: <uid>
Authorization: <token>
Content-Type: application/json; charset=utf-8
```

Responses use a standard JSON envelope:

```json
{"code": "1000", "msg": "...", "data": ...}
```

| `code` | Meaning | Verification status |
| --- | --- | --- |
| `"1000"` | Success (`data` holds the payload) | Verified live |
| `"1100"` | Token missing, invalid, or expired (~15-day lifetime) | Verified live |
| `"1300"` | Business/validation error (invalid parameters, wrong password or SMS code) | Verified live |

## Login

Successful login endpoints return:

```json
{"token": "<token>", "uid": 1001, "gid": 2002}
```

`uid` is the user ID sent in `caller_uid`; `gid` is the current home group ID required by device discovery.

### SMS verification-code login (verified live)

1. Request an SMS verification code:

   `POST /amcustomer/app/sms/sendcodenotlogin`

   ```json
   {"mobile": "13800000000", "smsType": "PHONE_LOGIN"}
   ```

2. Exchange the SMS code for a session token:

   `POST /amcustomer/app/userinfo/phone/login`

   ```json
   {
     "mobile": "13800000000",
     "smsCode": "123456",
     "appVersion": "2.10.1",
     "phoneModel": "Home Assistant",
     "phoneSysVersion": "1"
   }
   ```

### Password login (APK-derived; partially verified)

`POST /amcustomer/app/userinfo/login/ciphertext`

```json
{
  "mobile": "13800000000",
  "psword": "<base64-ciphertext>",
  "appVersion": "2.10.1",
  "phoneModel": "Home Assistant",
  "phoneSysVersion": "1"
}
```

The Android client encrypts the plaintext UTF-8 password as follows:

```text
key = SHA-256("Aidre@mSerta")          # 32-byte AES-256 key
ciphertext = AES-256-ECB-PKCS7(password)
psword = Base64(ciphertext)
```

**Verification note:** The live server accepted this ciphertext format and returned `code="1300"` on an intentional wrong-password test, confirming endpoint reachability and payload decoding. End-to-end password login with a valid account password was **not** tested live.

## Device discovery (verified live)

`GET /amdevice/app/device/gethomepage?gid=<gid>`

`data` contains `gid`, `uid`, and `hpDeviceDtoList`. Each entry in `hpDeviceDtoList` includes:

- `did` — numeric device ID used in bed control and report URLs
- `mac`, `pid`, `productCode` (`"E1SD"` on the tested bed), `nickName`, `online` (`"1"` / `"0"` or boolean)
- `patterns` — list of saved positions and modes configured on the account:

```json
{
  "patternId": 1,
  "patternName": "一键放平",
  "headAngle": 0,
  "waistAngle": 0,
  "legAngle": 0,
  "modeCtrl": 1
}
```

`modeCtrl` is preset-specific rather than a fixed `0=flat, 1=zero-gravity` enum: on the tested `E1SD`, the `一键放平` (flat) preset uses `modeCtrl: 1`. Clients recalling a preset should pass the `modeCtrl` value returned in that preset's definition.

## Property snapshot (verified live)

`GET /amelectricbed/app/propertysnapshot/getlocallist/<did>`

Returns an array of property objects (22 properties observed on `E1SD`):

```json
[
  {"did": 1234567, "identifier": "HeadAngle", "dataValue": "0"},
  {"did": 1234567, "identifier": "NightLight", "dataValue": "000000000100"},
  {"did": 1234567, "identifier": "FunctionSupport", "dataValue": "{\"HeadAngleMax\":60,\"LegAngleMax\":45,\"WaistAngleMax\":0}"}
]
```

`dataValue` is always a string:

- Values starting with `{` or `[` are JSON-encoded objects or arrays.
- Scalar numbers and schedule codes are plain strings. Do not coerce all digit strings to integers: `NightLight` uses significant leading zeros.

| Identifier | Meaning | Verification status |
| --- | --- | --- |
| `HeadAngle` | Current head angle in degrees | Verified live (`0` → `2` → `0`) |
| `LegAngle` | Current leg angle in degrees | Verified live (`0`) |
| `WaistAngle` | Current waist angle in degrees | Verified live (`0` on `E1SD`) |
| `FunctionSupport` | JSON object with `HeadAngleMax`, `LegAngleMax`, `WaistAngleMax` | Verified live (`60`, `45`, `0`) |
| `HeadState`, `LegState` | `{CurrentAngle, TargetAngle, Elasped, Timestamp}` while moving | Verified live (`HeadState.TargetAngle=2`) |
| `WaistState` | Movement state for waist axis | Inferred from APK |
| `OnBed` | Occupancy flag (`"0"` / `"1"`) | Verified live (`"1"`) |
| `ModeStatus` | Active mode object (includes `ModeCtrl`) | Verified live (`ModeStatus.ModeCtrl=1`) |
| `NightLight` | Under-bed light schedule and state string | Verified live (`"000000000100"`) |
| `ChildLock` | Child lock flag (`"0"` / `"1"`) | Read verified live (`"0"`); write unverified |
| `SnoreConf`, `WarningList` | Snore intervention config and mattress warnings | Seen in snapshot/APK; not used |
| `SideA:<key>`, `SideB:<key>` | Split-bed axis/state prefixes | Inferred from APK; single bed tested |

## Control

### Absolute angles (`angleset`, verified live)

`POST /amelectricbed/app/thingprop/angleset/<did>`

```json
{"headAngle": 2, "waistAngle": 0, "legAngle": 0, "modeCtrl": 0}
```

The endpoint requires the full set of angles on every call:

- For direct angle adjustments (`cover` or `number`), send `modeCtrl: 0` and include the current (or in-flight target) angles for unchanged axes so back-to-back commands do not reset another moving section.
- For preset recall (`button`), send `headAngle`, `waistAngle`, `legAngle`, and `modeCtrl` from the selected entry in `patterns` (verified live with `一键放平`, `modeCtrl: 1`).
- In the APK, presets that contain `patternDetails` entries with `identifier == "Massage"` also send `{"prop": {"Massage": <parsed dataValue>}}` to `thingprop/<did>` (implemented, not verified live).

### Single property (`thingprop`)

`POST /amelectricbed/app/thingprop/<did>`

```json
{"prop": {"NightLight": "100000000100"}}
```

Used for thing-model properties such as `NightLight`, `ChildLock`, `Massage`, and `SnoreConf`.

#### `NightLight` format

The cloud stores the under-bed light state and timer schedule as a fixed-width digit string:

- **12-character format (verified live on `E1SD`)**: `<on:1><startHH:2><startMM:2><endHH:2><endMM:2><brightness:3>`
  - `000000000100`: light off (`0`), schedule `00:00`–`00:00`, brightness `100`
  - `100000000100`: light on (`1`), schedule `00:00`–`00:00`, brightness `100`
- **9-character legacy format (inferred from APK)**: `<on:1><startHH:2><startMM:2><endHH:2><endMM:2>` (no brightness suffix).

To toggle the light without clobbering the user's schedule or brightness, replace only the first character (`"1"` or `"0"`) and keep `value[1:]` unchanged.

#### `ChildLock` format (inferred from APK)

`{"prop": {"ChildLock": 1}}` enables child lock and `{"prop": {"ChildLock": 0}}` disables it. Only reading `ChildLock="0"` from the snapshot was verified on the live bed.

## Sleep reports (verified live)

`POST /ammsreport/app/report/did/getday`

```json
{"did": 1234567, "day": "2026-10-25"}
```

- `day` must be formatted as `YYYY-MM-DD`; compact `YYYYMMDD` strings and future dates are rejected.
- `data` is `null` when no sleep report exists for the requested date.
- On the tested `E1SD`, a populated `data` object contained:
  - `score` (`95`) and `sleepTime` (`570`, total sleep duration in minutes)
  - `deep`, `light`, `rem`, `awake` — each `{percentage, value}` with `value` in minutes (`391`, `29`, `150`, `0`)
  - `heart_beat_avg` (`63` bpm) and `breath_avg` (`13` breaths/min)
  - `body_move` — array of `{time, value}` buckets (sum of `value` was `255` in the verified report)
  - `body_revolve` — array of `{time, value}` turn-over events (`9` entries in the verified report)
  - `snore_count` — array of snore events
  - `hrvResult` — `{daySdnn: 60, dayStress: 28, dayFatigued: 53, energyRecovery, fatigueEliminationPer, stressEliminationPer}`
  - `sleepQualityTagValue`, `textTagValue`, `tagKeys`
  - `time_start` and `time_end` (UTC epoch seconds)
- Related endpoints seen in the APK:
  - `POST /ammsreport/app/report/did/latest` was reachable live and returned `data: null` on the tested account.
  - `POST /ammsreport/app/report/did/getmonth` is APK-derived; parameter validation confirmed it requires a `month` parameter, but a full monthly report payload was not verified live.

## Transports present in the APK but not used

- **WebSocket and MQTT push**: the app can subscribe to `ws://nettypush.aidream.website/ws/<token>` or fetch MQTT credentials from `/ammessage/app/mqtt/access-credential`. Polling `getlocallist/<did>` over HTTPS is sufficient for Home Assistant and avoids maintaining a second persistent connection.
- **Local Wi-Fi HTTP (`/api/...`)**: `com.aidream.feature_bleprotocol.manager.localwifi` targets a separate air-mattress product family with surface pressure sensors and Server-Sent Events (SSE). It is not supported by ICF bed controllers.
- **Bluetooth Low Energy (BLE)**: used by the app for initial Wi-Fi provisioning and direct offline fallback; not required for cloud control.
