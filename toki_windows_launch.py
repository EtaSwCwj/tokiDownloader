"""Per-window relaunch properties: pin the application, not bare pythonw.exe."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

APP_ID = "EtaSwCwj.tokiDownloader.GUI.1"
PROPERTY_IDS = {"command": 2, "icon": 3, "displayName": 4, "appId": 5}
_runtime = {"applied": False, "error": "", "properties": {}}


def relaunch_properties(root):
    root = Path(root).resolve()
    return {
        "command": subprocess.list2cmdline([
            str(root / ".venv" / "Scripts" / "pythonw.exe"),
            str(root / "toki_launcher.py"), "launch",
        ]),
        "icon": str(root / "assets" / "toki-downloader.ico") + ",0",
        "displayName": "tokiDownloader",
        "appId": APP_ID,
    }


def window_properties(hwnd, values=None):
    """Read or set strings (None clears VT_EMPTY); returns the actual Windows values."""
    import ctypes as c
    from uuid import UUID

    class GUID(c.Structure):
        _fields_ = [("data", c.c_ubyte * 16)]

    class PROPERTYKEY(c.Structure):
        _fields_ = [("fmtid", GUID), ("pid", c.c_ulong)]

    class VariantData(c.Union):
        _fields_ = [("text", c.c_void_p), ("raw", c.c_byte * (16 if c.sizeof(c.c_void_p) == 8 else 8))]

    class PROPVARIANT(c.Structure):
        _fields_ = [("vt", c.c_ushort), ("reserved", c.c_ushort * 3), ("value", VariantData)]

    def guid(value):
        return GUID.from_buffer_copy(UUID(value).bytes_le)

    def check(hr):
        if hr < 0:
            raise OSError(f"Windows property store HRESULT 0x{hr & 0xFFFFFFFF:08X}")

    shell, ole = c.windll.shell32, c.windll.ole32
    get_store = shell.SHGetPropertyStoreForWindow
    get_store.argtypes = [c.c_void_p, c.POINTER(GUID), c.POINTER(c.c_void_p)]
    get_store.restype = c.c_long
    ole.PropVariantClear.argtypes = [c.POINTER(PROPVARIANT)]
    ole.PropVariantClear.restype = c.c_long
    store = c.c_void_p()
    iid = guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")
    check(get_store(int(hwnd), c.byref(iid), c.byref(store)))
    table = c.cast(store, c.POINTER(c.POINTER(c.c_void_p))).contents
    release = c.WINFUNCTYPE(c.c_ulong, c.c_void_p)(table[2])
    get_value = c.WINFUNCTYPE(c.c_long, c.c_void_p, c.POINTER(PROPERTYKEY), c.POINTER(PROPVARIANT))(table[5])
    set_value = c.WINFUNCTYPE(c.c_long, c.c_void_p, c.POINTER(PROPERTYKEY), c.POINTER(PROPVARIANT))(table[6])
    fmtid = guid("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3")
    result = {}
    try:
        for name, number in PROPERTY_IDS.items():
            key, variant = PROPERTYKEY(fmtid, number), PROPVARIANT()
            if values is not None and name in values:
                # SetValue copies the string. This temporary Python-owned buffer
                # must not be freed with PropVariantClear/CoTaskMemFree.
                if values[name] is not None:
                    buffer = c.create_unicode_buffer(values[name])
                    variant.vt = 31  # VT_LPWSTR
                    variant.value.text = c.cast(buffer, c.c_void_p)
                check(set_value(store, c.byref(key), c.byref(variant)))
                variant = PROPVARIANT()
            try:
                check(get_value(store, c.byref(key), c.byref(variant)))
                result[name] = c.wstring_at(variant.value.text) if variant.vt == 31 and variant.value.text else ""
            finally:
                ole.PropVariantClear(c.byref(variant))
    finally:
        release(store)
    return result


def apply_window_relaunch(hwnd, root, *, native=None):
    desired = relaunch_properties(root)
    if os.name != "nt" and native is None:
        return {"applied": False, "error": "Windows only", "properties": desired}
    try:
        actual = (native or window_properties)(hwnd, desired)
        if actual != desired:
            raise OSError("Windows relaunch property verification failed")
        _runtime.update(applied=True, error="", properties=actual)
    except Exception as error:
        _runtime.update(applied=False, error=str(error), properties=desired)
    return dict(_runtime)


def relaunch_snapshot():
    return dict(_runtime)


def notify_shortcut_changed(path):
    import ctypes as c
    notify = c.windll.shell32.SHChangeNotify
    notify.argtypes = [c.c_long, c.c_uint, c.c_wchar_p, c.c_void_p]
    notify.restype = None
    # UPDATEITEM / PATHW | FLUSHNOWAIT: refresh just this item, no Explorer restart.
    notify(0x00002000, 0x0005 | 0x3000, str(path), None)


def clear_window_relaunch(hwnd):
    if os.name == "nt":
        try:
            window_properties(hwnd, {name: None for name in PROPERTY_IDS})
        except OSError:
            pass
