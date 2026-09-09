"""按进程枚举 Windows 音频会话（WASAPI IAudioSessionManager2，comtypes 封装）。

用途：视频录制「系统声音（内录）」改为按**正在发声的应用**选择来源，
而不是让用户面对一堆声卡设备名。每个活跃会话 = {pid, 进程名, 设备名}。

依赖：comtypes（纯 Python，无二进制数据文件）。
Qt 兼容：comtypes 在 import 时按 sys.coinit_flags 初始化 COM（默认 STA），
PySide6 主线程可能已是 MTA，故在 import 前强制 sys.coinit_flags=0（MTA），
同模式重复初始化返回 S_FALSE 不抛错；WASAPI 会话 API 在 MTA 下可用。
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import POINTER, wintypes

# comtypes import 时按此 flags 调用 CoInitializeEx（0 = COINIT_MULTITHREADED）。
# 注意：comtypes 在 import 时无条件做模块级 COM 初始化，而 PySide6 主线程已注册
# COM 模式（真实窗口环境为 STA），在主线程 import 必然 RPC_E_CHANGED_MODE。
# 因此本模块**延迟 import comtypes**：list_active_sessions() 须在**独立工作线程**
# 中调用（线程未初始化 COM → comtypes 按 sys.coinit_flags 初始化成功，WASAPI 会话
# 枚举在 MTA 下可用），UI 侧已用 QThread 包裹（见 video_page._refresh_loopback_sessions）。
sys.coinit_flags = 0


def _match_thread_com_mode() -> None:
    """探测当前线程已注册的 COM 模式，并把 sys.coinit_flags 设为同模式。

    comtypes 在 import 时按 sys.coinit_flags 做模块级 CoInitializeEx；若与当前
    线程已注册模式不符会抛 RPC_E_CHANGED_MODE。PySide6 主线程（真实窗口环境）
    会预先初始化 COM（模式因平台/插件而异），故 import comtypes 前先探测匹配。
    """
    S_OK, S_FALSE = 0, 1
    try:
        hr = ctypes.windll.ole32.CoInitializeEx(None, 2)  # 试 STA
        if hr in (S_OK, S_FALSE):
            sys.coinit_flags = 2
            return
    except Exception:
        pass
    try:
        hr = ctypes.windll.ole32.CoInitializeEx(None, 0)  # 试 MTA
        if hr in (S_OK, S_FALSE):
            sys.coinit_flags = 0
    except Exception:
        pass


_match_thread_com_mode()

import comtypes  # noqa: E402
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown  # noqa: E402
CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IAudioSessionManager2 = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
PKEY_Device_FriendlyName_fmtid = GUID("{A45C254E-DF1C-4EFD-8020-67D146A850E0}")

eRender = 0
DEVICE_STATE_ACTIVE = 0x00000001
STGM_READ = 0
CLSCTX_ALL = 0x17

AudioSessionStateActive = 1

VT_LPWSTR = 31
VT_LPSTR = 30


# ---------------------------------------------------------------- 结构体 ----
class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    """仅用于读取字符串值的简化 PROPVARIANT（16 字节，64 位对齐）。"""
    _fields_ = [
        ("vt", wintypes.USHORT),
        ("wReserved1", wintypes.USHORT),
        ("wReserved2", wintypes.USHORT),
        ("wReserved3", wintypes.USHORT),
        ("_val", ctypes.c_void_p),
    ]

    @property
    def pwszVal(self) -> str | None:
        return ctypes.cast(self._val, ctypes.c_wchar_p).value

    @property
    def pszVal(self) -> bytes | None:
        return ctypes.cast(self._val, ctypes.c_char_p).value


# ---------------------------------------------------------------- COM 接口 ----
class IPropertyStore(IUnknown):
    _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_ = (
        COMMETHOD([], HRESULT, "GetCount",
                  (["out"], POINTER(wintypes.DWORD), "cProps")),
        COMMETHOD([], HRESULT, "GetAt",
                  (["in"], wintypes.DWORD, "iProp"),
                  (["out"], POINTER(PROPERTYKEY), "pkey")),
        COMMETHOD([], HRESULT, "GetValue",
                  (["in"], POINTER(PROPERTYKEY), "key"),
                  (["out"], POINTER(PROPVARIANT), "pv")),
        COMMETHOD([], HRESULT, "SetValue",
                  (["in"], POINTER(PROPERTYKEY), "key"),
                  (["in"], POINTER(PROPVARIANT), "propvar")),
        COMMETHOD([], HRESULT, "Commit"),
    )


class IAudioSessionControl(IUnknown):
    _iid_ = GUID("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")
    _methods_ = (
        COMMETHOD([], HRESULT, "GetState",
                  (["out"], POINTER(ctypes.c_int), "pRetVal")),
        COMMETHOD([], HRESULT, "GetDisplayName",
                  (["out"], POINTER(ctypes.c_wchar_p), "pRetVal")),
        COMMETHOD([], HRESULT, "SetDisplayName",
                  (["in"], ctypes.c_wchar_p, "Value"),
                  (["in"], POINTER(GUID), "EventContext")),
        COMMETHOD([], HRESULT, "GetIconPath",
                  (["out"], POINTER(ctypes.c_wchar_p), "pRetVal")),
        COMMETHOD([], HRESULT, "SetIconPath",
                  (["in"], ctypes.c_wchar_p, "Value"),
                  (["in"], POINTER(GUID), "EventContext")),
        COMMETHOD([], HRESULT, "GetGroupingParam",
                  (["out"], POINTER(GUID), "pRetVal")),
        COMMETHOD([], HRESULT, "SetGroupingParam",
                  (["in"], POINTER(GUID), "Override"),
                  (["in"], POINTER(GUID), "EventContext")),
        COMMETHOD([], HRESULT, "RegisterAudioSessionNotification",
                  (["in"], POINTER(ctypes.c_void_p), "NewNotifications")),
        COMMETHOD([], HRESULT, "UnregisterAudioSessionNotification",
                  (["in"], POINTER(ctypes.c_void_p), "NewNotifications")),
    )


class IAudioSessionControl2(IAudioSessionControl):
    _iid_ = GUID("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")
    _methods_ = (
        COMMETHOD([], HRESULT, "GetSessionIdentifier",
                  (["out"], POINTER(ctypes.c_wchar_p), "pRetVal")),
        COMMETHOD([], HRESULT, "GetSessionInstanceIdentifier",
                  (["out"], POINTER(ctypes.c_wchar_p), "pRetVal")),
        COMMETHOD([], HRESULT, "GetProcessId",
                  (["out"], POINTER(wintypes.DWORD), "pRetVal")),
        COMMETHOD([], HRESULT, "IsSystemSoundsSession",
                  (["out"], POINTER(wintypes.BOOL), "pRetVal")),
        COMMETHOD([], HRESULT, "SetDuckingPreference",
                  (["in"], wintypes.BOOL, "optOut")),
    )


class IAudioSessionEnumerator(IUnknown):
    _iid_ = GUID("{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}")
    _methods_ = (
        COMMETHOD([], HRESULT, "GetCount",
                  (["out"], POINTER(ctypes.c_int), "SessionCount")),
        COMMETHOD([], HRESULT, "GetSession",
                  (["in"], ctypes.c_int, "SessionCount"),
                  (["out"], POINTER(POINTER(IAudioSessionControl)), "ppSession")),
    )


class IAudioSessionManager(IUnknown):
    _iid_ = GUID("{BFA971F1-4D5E-40BB-935E-967039BFBEE4}")
    _methods_ = (
        COMMETHOD([], HRESULT, "GetAudioSessionControl",
                  (["in"], POINTER(GUID), "AudioSessionGuid"),
                  (["in"], wintypes.DWORD, "StreamFlags"),
                  (["out"], POINTER(POINTER(IAudioSessionControl)), "ppSessionControl")),
        COMMETHOD([], HRESULT, "GetSimpleAudioVolume",
                  (["in"], POINTER(GUID), "AudioSessionGuid"),
                  (["in"], wintypes.DWORD, "StreamFlags"),
                  (["out"], POINTER(POINTER(ctypes.c_void_p)), "ppAudioVolume")),
    )


class IAudioSessionManager2(IAudioSessionManager):
    _iid_ = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
    _methods_ = (
        COMMETHOD([], HRESULT, "GetSessionEnumerator",
                  (["out"], POINTER(POINTER(IAudioSessionEnumerator)), "SessionEnum")),
        COMMETHOD([], HRESULT, "RegisterSessionNotification",
                  (["in"], POINTER(ctypes.c_void_p), "SessionNotification")),
        COMMETHOD([], HRESULT, "UnregisterSessionNotification",
                  (["in"], POINTER(ctypes.c_void_p), "SessionNotification")),
        COMMETHOD([], HRESULT, "RegisterDuckNotification",
                  (["in"], ctypes.c_wchar_p, "sessionID"),
                  (["in"], POINTER(ctypes.c_void_p), "duckNotification")),
        COMMETHOD([], HRESULT, "UnregisterDuckNotification",
                  (["in"], POINTER(ctypes.c_void_p), "duckNotification")),
    )


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = (
        COMMETHOD([], HRESULT, "Activate",
                  (["in"], POINTER(GUID), "iid"),
                  (["in"], wintypes.DWORD, "dwClsCtx"),
                  (["in"], POINTER(PROPVARIANT), "pActivationParams"),
                  (["out"], POINTER(POINTER(IAudioSessionManager2)), "ppInterface")),
        COMMETHOD([], HRESULT, "OpenPropertyStore",
                  (["in"], wintypes.DWORD, "stgmAccess"),
                  (["out"], POINTER(POINTER(IPropertyStore)), "ppProperties")),
        COMMETHOD([], HRESULT, "GetId",
                  (["out"], POINTER(ctypes.c_wchar_p), "ppstrId")),
        COMMETHOD([], HRESULT, "GetState",
                  (["out"], POINTER(wintypes.DWORD), "pdwState")),
    )


class IMMDeviceCollection(IUnknown):
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
    _methods_ = (
        COMMETHOD([], HRESULT, "GetCount",
                  (["out"], POINTER(wintypes.DWORD), "pcDevices")),
        COMMETHOD([], HRESULT, "Item",
                  (["in"], wintypes.DWORD, "nDevice"),
                  (["out"], POINTER(POINTER(IMMDevice)), "ppDevice")),
    )


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = (
        COMMETHOD([], HRESULT, "EnumAudioEndpoints",
                  (["in"], wintypes.DWORD, "dataFlow"),
                  (["in"], wintypes.DWORD, "dwStateMask"),
                  (["out"], POINTER(POINTER(IMMDeviceCollection)), "ppDevices")),
        COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint",
                  (["in"], wintypes.DWORD, "dataFlow"),
                  (["in"], wintypes.DWORD, "role"),
                  (["out"], POINTER(POINTER(IMMDevice)), "ppEndpoint")),
        COMMETHOD([], HRESULT, "GetDevice",
                  (["in"], ctypes.c_wchar_p, "pwstrId"),
                  (["out"], POINTER(POINTER(IMMDevice)), "ppDevice")),
        COMMETHOD([], HRESULT, "RegisterEndpointNotificationCallback",
                  (["in"], POINTER(ctypes.c_void_p), "pClient")),
        COMMETHOD([], HRESULT, "UnregisterEndpointNotificationCallback",
                  (["in"], POINTER(ctypes.c_void_p), "pClient")),
    )


# ---------------------------------------------------------------- 工具 ----
def _process_name(pid: int) -> str:
    """按 pid 取进程名（QueryFullProcessImageNameW）。"""
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return f"pid{pid}"
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
            return f"pid{pid}"
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        return f"pid{pid}"


def _device_friendly_name(dev: IMMDevice) -> str:
    """IMMDevice → PropertyStore → PKEY_Device_FriendlyName。"""
    key = PROPERTYKEY()
    key.fmtid = PKEY_Device_FriendlyName_fmtid
    key.pid = 14
    try:
        ps = dev.OpenPropertyStore(STGM_READ)
        pv = ps.GetValue(ctypes.byref(key))
        if pv.vt == VT_LPWSTR and pv.pwszVal:
            return pv.pwszVal
        if pv.vt == VT_LPSTR and pv.pszVal:
            return pv.pszVal.decode("gbk", "ignore")
    except Exception:
        pass
    return ""


def _free_string(ptr) -> None:
    if ptr:
        ctypes.windll.ole32.CoTaskMemFree(ptr)


def _co_init_compatible() -> bool:
    """按当前线程已注册的 COM 模式初始化（comtypes.CoInitialize 硬编码 STA，
    在 MTA 线程会 RPC_E_CHANGED_MODE；这里先试 sys.coinit_flags 模式，冲突则换另一模式）。"""
    want = getattr(sys, "coinit_flags", 0)
    for flags in (want, 2 if want == 0 else 0):
        try:
            comtypes.CoInitializeEx(flags)
            return True
        except OSError:
            continue
    return False


def list_active_sessions(max_per_device: int = 64, _debug: bool = False) -> list[dict]:
    """枚举当前**正在发声**（Active 状态）的音频会话。

    返回 [ {pid, process_name, device_name, display_name}, ... ]，
    按设备分组枚举，每个会话天然带它所在输出设备的友好名。
    没有正在发声的程序时返回空列表。
    """
    results: list[dict] = []
    if not _co_init_compatible():
        return results
    try:
        enum = comtypes.CoCreateInstance(
            CLSID_MMDeviceEnumerator, interface=IMMDeviceEnumerator)
        devs = enum.EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE)
        n = devs.GetCount()
        for i in range(min(n, 16)):
            try:
                dev = devs.Item(i)
            except Exception as e:
                if _debug:
                    print("[audio_sessions] Item:", repr(e))
                continue
            dev_name = _device_friendly_name(dev)
            if not dev_name:
                continue
            try:
                mgr = dev.Activate(IID_IAudioSessionManager2, CLSCTX_ALL, None)
            except Exception as e:
                if _debug:
                    print(f"[audio_sessions] {dev_name} Activate:", repr(e))
                continue
            try:
                sess_enum = mgr.GetSessionEnumerator()
                count = sess_enum.GetCount()
                for j in range(min(count, max_per_device)):
                    try:
                        ctl = sess_enum.GetSession(j)
                        if not ctl:
                            continue
                        state = ctl.GetState()
                        if state != AudioSessionStateActive:
                            continue
                        ctl2 = ctl.QueryInterface(IAudioSessionControl2)
                        pid = ctl2.GetProcessId()
                        disp = ctl.GetDisplayName()
                        disp_str = ""
                        if disp:
                            disp_str = disp
                            _free_string(disp)
                        results.append({
                            "pid": int(pid),
                            "process_name": _process_name(pid),
                            "device_name": dev_name,
                            "display_name": (disp_str or "").strip(),
                        })
                    except Exception:
                        continue
            except Exception as e:
                if _debug:
                    print(f"[audio_sessions] {dev_name} 枚举:", repr(e))
                continue
        # 按 pid+设备去重（同进程可能多会话）
        seen = set()
        dedup = []
        for r in results:
            k = (r["pid"], r["device_name"])
            if k not in seen:
                seen.add(k)
                dedup.append(r)
        return dedup
    except Exception:
        return results
    finally:
        try:
            comtypes.CoUninitialize()
        except Exception:
            pass


if __name__ == "__main__":
    sessions = list_active_sessions(_debug=True)
    print(f"活跃会话数: {len(sessions)}")
    for s in sessions:
        print(f"  {s['process_name']} | {s['device_name']} | {s['display_name']}")
