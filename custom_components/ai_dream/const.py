"""Constants for the AI Dream integration."""

from dataclasses import dataclass

DOMAIN = "ai_dream"

BASE_URL = "https://appapi.aidream.website"

SERVICE_CUSTOMER = "amcustomer"
SERVICE_DEVICE = "amdevice"
SERVICE_BED = "amelectricbed"
SERVICE_REPORT = "ammsreport"

PATH_SMS_CODE = f"/{SERVICE_CUSTOMER}/app/sms/sendcodenotlogin"
PATH_LOGIN_SMS = f"/{SERVICE_CUSTOMER}/app/userinfo/phone/login"
PATH_LOGIN_PASSWORD = f"/{SERVICE_CUSTOMER}/app/userinfo/login/ciphertext"
PATH_DEVICES = f"/{SERVICE_DEVICE}/app/device/gethomepage"
PATH_ALL_STATE = f"/{SERVICE_BED}/app/propertysnapshot/getlocallist/{{did}}"
PATH_ANGLESET = f"/{SERVICE_BED}/app/thingprop/angleset/{{did}}"
PATH_THINGPROP = f"/{SERVICE_BED}/app/thingprop/{{did}}"
PATH_DAY_REPORT = f"/{SERVICE_REPORT}/app/report/did/getday"

# The Android client encrypts the password with AES/ECB/PKCS5Padding using
# SHA-256("Aidre@mSerta") as the 256-bit key.
PASSWORD_KEY = "Aidre@mSerta"
SMS_TYPE_LOGIN = "PHONE_LOGIN"

DEFAULT_SCAN_INTERVAL = 30
REQUEST_TIMEOUT = 20

CONF_PHONE = "phone"
CONF_PASSWORD = "password"
CONF_SMS_CODE = "sms_code"
CONF_TOKEN = "token"
CONF_UID = "uid"
CONF_GID = "gid"
CONF_DID = "did"
CONF_DEVICE_NAME = "device_name"
CONF_PRODUCT_CODE = "product_code"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLE_WAIST = "enable_waist"

# Axis property names used by the cloud thing model.
PROP_HEAD_ANGLE = "headAngle"
PROP_WAIST_ANGLE = "waistAngle"
PROP_LEG_ANGLE = "legAngle"

SNAPSHOT_HEAD_ANGLE = "HeadAngle"
SNAPSHOT_WAIST_ANGLE = "WaistAngle"
SNAPSHOT_LEG_ANGLE = "LegAngle"
SNAPSHOT_ON_BED = "OnBed"
SNAPSHOT_NIGHT_LIGHT = "NightLight"
SNAPSHOT_CHILD_LOCK = "ChildLock"


@dataclass(frozen=True, kw_only=True)
class Axis:
    """One motorised axis and its cloud identifiers."""

    key: str
    prop: str
    state_key: str
    icon: str
    max_angle: int


AXES: tuple[Axis, ...] = (
    Axis(
        key="head_angle",
        prop=PROP_HEAD_ANGLE,
        state_key="HeadState",
        icon="mdi:bed-clock",
        max_angle=60,
    ),
    Axis(
        key="leg_angle",
        prop=PROP_LEG_ANGLE,
        state_key="LegState",
        icon="mdi:bed",
        max_angle=45,
    ),
    Axis(
        key="waist_angle",
        prop=PROP_WAIST_ANGLE,
        state_key="WaistState",
        icon="mdi:human-handsup",
        max_angle=8,
    ),
)

SIDE_PREFIXES = ("SideA:", "SideB:")
