"""
BlueZ GATT peripheral for MedSim IP-800 (dbus-fast / asyncio).

We deliberately drop down to the BlueZ D-Bus level instead of a high-level
library, because we need ATTRIBUTION: every ReadValue/WriteValue from BlueZ
carries options['device'] = the connection's object path, which gives us the
BLE address. That is the basis for per-player flags.

Requires running on Linux with BlueZ (tested on a Raspberry Pi). On a dev
machine without BLE, run main.py --mock instead.
"""

import asyncio

try:
    from dbus_fast.aio import MessageBus
    from dbus_fast.service import ServiceInterface, method, dbus_property
    from dbus_fast import Variant, BusType, PropertyAccess
    HAVE_DBUS = True
except Exception:  # pragma: no cover - missing on a dev machine
    HAVE_DBUS = False
    ServiceInterface = object  # so the class definitions below do not crash

from . import config


BLUEZ = "org.bluez"
GATT_MANAGER = "org.bluez.GattManager1"
LE_ADV_MANAGER = "org.bluez.LEAdvertisingManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
LE_ADV_IFACE = "org.bluez.LEAdvertisement1"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"

APP_PATH = "/com/medsim/app"


def _addr_from_options(options) -> str:
    """Extract 'dev_AA_BB_..' from BlueZ options['device']."""
    dev = options.get("device") if options else None
    if dev is None:
        return "unknown"
    path = dev.value if hasattr(dev, "value") else str(dev)
    return path.rsplit("/", 1)[-1]   # last segment: dev_AA_BB_CC_DD_EE_FF


# ---------------------------------------------------------------------------
# D-Bus objects
# ---------------------------------------------------------------------------
if HAVE_DBUS:

    class Characteristic(ServiceInterface):
        def __init__(self, path, uuid, flags, service_path,
                     read_cb=None, write_cb=None, notify=False):
            super().__init__(GATT_CHRC_IFACE)
            self._path = path
            self._uuid = uuid
            self._flags = flags
            self._service_path = service_path
            self._read_cb = read_cb
            self._write_cb = write_cb
            self._value = bytearray()
            self._notifying = False
            self._can_notify = notify

        # --- properties ---
        @dbus_property(access=PropertyAccess.READ)
        def UUID(self) -> "s":
            return self._uuid

        @dbus_property(access=PropertyAccess.READ)
        def Service(self) -> "o":
            return self._service_path

        @dbus_property(access=PropertyAccess.READ)
        def Flags(self) -> "as":
            return self._flags

        @dbus_property(access=PropertyAccess.READ)
        def Value(self) -> "ay":
            return bytes(self._value)

        @dbus_property(access=PropertyAccess.READ)
        def Notifying(self) -> "b":
            return self._notifying

        # --- methods ---
        @method()
        def ReadValue(self, options: "a{sv}") -> "ay":
            addr = _addr_from_options(options)
            try:
                if self._read_cb:
                    data = self._read_cb(addr)
                    if data is not None:
                        self._value = bytearray(data)
                # Honor the read offset so long values (> MTU) reassemble
                # correctly across Read Blob requests. BlueZ passes 'offset'.
                off = options.get("offset")
                offset = off.value if off is not None and hasattr(off, "value") else 0
                return bytes(self._value)[offset:]
            except Exception:
                import traceback
                print(f"[ble] ReadValue error on {self._uuid} addr={addr}:")
                traceback.print_exc()
                raise

        @method()
        def WriteValue(self, value: "ay", options: "a{sv}"):
            addr = _addr_from_options(options)
            try:
                if self._write_cb:
                    self._write_cb(addr, bytes(value))
            except Exception:
                import traceback
                print(f"[ble] WriteValue error on {self._uuid}:")
                traceback.print_exc()
                raise

        @method()
        def StartNotify(self):
            self._notifying = True

        @method()
        def StopNotify(self):
            self._notifying = False

        # --- server push ---
        def notify(self, data: bytes):
            self._value = bytearray(data)
            if self._notifying:
                self.emit_properties_changed({"Value": bytes(data)})

        # --- for the ObjectManager ---
        def props(self):
            return {
                GATT_CHRC_IFACE: {
                    "UUID": Variant("s", self._uuid),
                    "Service": Variant("o", self._service_path),
                    "Flags": Variant("as", self._flags),
                }
            }

    class Service(ServiceInterface):
        def __init__(self, path, uuid, primary=True):
            super().__init__(GATT_SERVICE_IFACE)
            self._path = path
            self._uuid = uuid
            self._primary = primary

        @dbus_property(access=PropertyAccess.READ)
        def UUID(self) -> "s":
            return self._uuid

        @dbus_property(access=PropertyAccess.READ)
        def Primary(self) -> "b":
            return self._primary

        def props(self):
            return {
                GATT_SERVICE_IFACE: {
                    "UUID": Variant("s", self._uuid),
                    "Primary": Variant("b", self._primary),
                }
            }

    class Application(ServiceInterface):
        def __init__(self):
            super().__init__(DBUS_OM_IFACE)
            self.services = []
            self.chars = []

        @method()
        def GetManagedObjects(self) -> "a{oa{sa{sv}}}":
            managed = {}
            for s in self.services:
                managed[s._path] = s.props()
            for c in self.chars:
                managed[c._path] = c.props()
            return managed

    class Advertisement(ServiceInterface):
        def __init__(self, path, local_name, service_uuids):
            super().__init__(LE_ADV_IFACE)
            self._path = path
            self._local_name = local_name
            self._service_uuids = service_uuids

        @dbus_property(access=PropertyAccess.READ)
        def Type(self) -> "s":
            return "peripheral"

        @dbus_property(access=PropertyAccess.READ)
        def ServiceUUIDs(self) -> "as":
            return self._service_uuids

        @dbus_property(access=PropertyAccess.READ)
        def LocalName(self) -> "s":
            return self._local_name

        @dbus_property(access=PropertyAccess.READ)
        def Includes(self) -> "as":
            return ["tx-power"]

        @method()
        def Release(self):
            pass


# ---------------------------------------------------------------------------
# The server
# ---------------------------------------------------------------------------
class BLEServer:
    """Builds the GATT tree and wires the handlers to the controller."""

    def __init__(self, controller, adapter="hci0"):
        if not HAVE_DBUS:
            raise RuntimeError(
                "dbus-fast missing / no BlueZ. Run with --mock on a dev machine."
            )
        self.controller = controller
        self.adapter_path = f"/org/bluez/{adapter}"
        self.bus = None
        self.app = Application()
        self._chars_by_uuid = {}

    # ------------------------------------------------------------
    def _add_service(self, uuid, idx):
        path = f"{APP_PATH}/service{idx}"
        svc = Service(path, uuid)
        self.app.services.append(svc)
        return path

    def _add_char(self, service_path, cidx, uuid, flags,
                  read_cb=None, write_cb=None, notify=False):
        path = f"{service_path}/char{cidx}"
        c = Characteristic(path, uuid, flags, service_path,
                           read_cb=read_cb, write_cb=write_cb, notify=notify)
        self.app.chars.append(c)
        self._chars_by_uuid[uuid] = c
        return c

    def _build_tree(self):
        ctl = self.controller

        # --- Device Information ---
        s = self._add_service(config.DIS_SERVICE, 0)
        self._add_char(s, 0, config.CHAR_MANUFACTURER, ["read"],
                       read_cb=lambda a: config.DIS_MANUFACTURER.encode())
        self._add_char(s, 1, config.CHAR_MODEL_NUMBER, ["read"],
                       read_cb=ctl.read_model_number)     # grants F1
        self._add_char(s, 2, config.CHAR_SERIAL_NUMBER, ["read"],
                       read_cb=lambda a: config.DIS_SERIAL.encode())
        self._add_char(s, 3, config.CHAR_FIRMWARE_REV, ["read"],
                       read_cb=lambda a: config.DIS_FIRMWARE.encode())  # hides the key
        self._add_char(s, 4, config.CHAR_HARDWARE_REV, ["read"],
                       read_cb=lambda a: config.DIS_HARDWARE.encode())

        # --- Battery ---
        s = self._add_service(config.BATTERY_SERVICE, 1)
        self._add_char(s, 0, config.CHAR_BATTERY_LEVEL, ["read", "notify"],
                       read_cb=lambda a: bytes([87]), notify=True)

        # --- Heart Rate (patient telemetry) ---
        s = self._add_service(config.HR_SERVICE, 2)
        self._add_char(s, 0, config.CHAR_HR_MEASUREMENT, ["read", "notify"],
                       read_cb=lambda a: ctl.hr_measurement(), notify=True)

        # --- Insulin Delivery Service (simplified) ---
        s = self._add_service(config.IDS_SERVICE, 3)
        self._add_char(s, 0, config.CHAR_IDD_FEATURES, ["read"],
                       read_cb=ctl.read_features)          # grants F2
        self._add_char(s, 1, config.CHAR_IDD_STATUS, ["read", "notify"],
                       read_cb=lambda a: ctl.status_payload(), notify=True)
        self._add_char(s, 2, config.CHAR_IDD_CCP, ["write", "write-without-response"],
                       write_cb=ctl.handle_ccp)            # the attack surface

        # --- CTF service ---
        s = self._add_service(config.CTF_SERVICE, 4)
        self._add_char(s, 0, config.CHAR_PLAYER_NAME, ["read", "write"],
                       read_cb=ctl.read_player_name, write_cb=ctl.write_player_name)
        self._add_char(s, 1, config.CHAR_FLAG, ["read"],
                       read_cb=ctl.read_flags)
        self._add_char(s, 2, config.CHAR_SUBMIT_FLAG, ["write", "read"],
                       read_cb=ctl.read_submit_result, write_cb=ctl.submit_flag)
        self._add_char(s, 3, config.CHAR_SCORE, ["read"],
                       read_cb=ctl.read_score)

    # ------------------------------------------------------------
    async def start(self):
        self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        self._build_tree()

        # export all objects
        self.bus.export(APP_PATH, self.app)
        for s in self.app.services:
            self.bus.export(s._path, s)
        for c in self.app.chars:
            self.bus.export(c._path, c)

        adv = Advertisement(f"{APP_PATH}/adv0", config.DEVICE_NAME,
                            [config.IDS_SERVICE])
        self.bus.export(adv._path, adv)

        # power on the adapter + set Alias
        introspection = await self.bus.introspect(BLUEZ, self.adapter_path)
        adapter_obj = self.bus.get_proxy_object(BLUEZ, self.adapter_path, introspection)
        props = adapter_obj.get_interface(DBUS_PROP_IFACE)
        await props.call_set("org.bluez.Adapter1", "Powered", Variant("b", True))
        try:
            await props.call_set("org.bluez.Adapter1", "Alias",
                                 Variant("s", config.DEVICE_NAME))
        except Exception:
            pass

        gatt_mgr = adapter_obj.get_interface(GATT_MANAGER)
        await gatt_mgr.call_register_application(APP_PATH, {})

        adv_mgr = adapter_obj.get_interface(LE_ADV_MANAGER)
        await adv_mgr.call_register_advertisement(adv._path, {})

    # ------------------------------------------------------------
    def push_status(self, data: bytes):
        c = self._chars_by_uuid.get(config.CHAR_IDD_STATUS)
        if c:
            c.notify(data)

    def push_hr(self, data: bytes):
        c = self._chars_by_uuid.get(config.CHAR_HR_MEASUREMENT)
        if c:
            c.notify(data)
