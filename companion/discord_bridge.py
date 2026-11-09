#!/usr/bin/env python3
"""Companion bridge for KodiCord.

Run this on the PC that hosts your Discord client. It exposes a tiny HTTP
API that the Kodi addon talks to, and forwards Rich Presence updates to the
local Discord IPC socket.

Usage:
    python3 discord_bridge.py --client-id 123456789012345678 --port 8765 --token secret
"""

import argparse
import base64
import json
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from discord_ipc import DiscordIPC, DiscordIPCError

try:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
except ImportError:  # py2 fallback not expected
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer as ThreadingHTTPServer


class BridgeState:
    def __init__(self, client_id, token=""):
        self.client_id = client_id
        self.token = token
        self.ipc = None
        self.lock = threading.Lock()

    def _connect(self):
        try:
            if self.ipc is not None:
                try:
                    self.ipc.close()
                except Exception:
                    pass
            self.ipc = DiscordIPC(self.client_id)
            self.ipc.connect(timeout=5)
            return True
        except Exception as e:
            self.ipc = None
            print("[bridge] connect failed: %s" % e)
            return False

    def ensure(self):
        with self.lock:
            if self.ipc is not None and self.ipc.connected:
                return True
            return self._connect()

    def update(self, activity):
        if not self.ensure():
            return False
        try:
            with self.lock:
                self.ipc.set_activity(activity)
            return True
        except Exception as e:
            print("[bridge] update failed: %s" % e)
            with self.lock:
                try:
                    if self.ipc is not None:
                        self.ipc.close()
                except Exception:
                    pass
                self.ipc = None
            return False

    def clear(self):
        return self.update(None)


STATE = None
_TRAY_INSTANCE = None

try:
    import winreg
except Exception:
    winreg = None


class Handler(BaseHTTPRequestHandler):
    def _auth_ok(self):
        if not STATE.token:
            return True
        return self.headers.get("X-Auth-Token", "") == STATE.token

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/ping":
            if not self._auth_ok():
                self._send_json(401, {"ok": False})
                return
            self._send_json(200, {"ok": True, "connected": STATE.ensure()})
            return
        self._send_json(404, {"ok": False})

    def do_POST(self):
        path = self.path.split("?")[0]
        if not self._auth_ok():
            self._send_json(401, {"ok": False})
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw.decode("utf-8", "replace") or "{}")
        except Exception:
            data = {}
        if path == "/activity":
            if data.get("clear"):
                print("[bridge] clear")
                try:
                    STATE.ipc.clear()
                    ok = True
                except Exception:
                    ok = False
                self._send_json(200 if ok else 503, {"ok": ok})
                return
            if "activity" in data:
                ok = STATE.update(data.get("activity"))
                self._send_json(200 if ok else 503, {"ok": ok})
                return
            # metadata-style request -> use DiscordIPC.update_activity
            notify = bool(data.pop("notify", False))
            print("[bridge] %s | %s | thumb=%s | url=%s" % (
                data.get("media_type"), data.get("title"),
                data.get("thumbnail"), data.get("media_url")))
            try:
                if not STATE.ensure():
                    self._send_json(503, {"ok": False})
                    return
                ok = STATE.ipc.update_activity(**data)
                resp = getattr(STATE.ipc, "last_response", None)
                if isinstance(resp, dict) and resp.get("evt") == "ERROR":
                    print("[bridge] Discord rejected activity: %s" % (resp.get("data"),))
                    ok = False
                if ok and notify:
                    try:
                        mtype = data.get("media_type") or "video"
                        title = (data.get("title") or "").strip()
                        artist = (data.get("artist") or "").strip()
                        if mtype == "music" and artist and title:
                            msg = "%s - %s" % (artist, title)
                        elif title:
                            msg = title
                        elif artist:
                            msg = artist
                        else:
                            msg = "New media playing"
                        _notify_tray("KodiCord", msg)
                    except Exception:
                        pass
                self._send_json(200 if ok else 503, {"ok": ok})
            except Exception as e:
                print("[bridge] update_activity failed: %s" % e)
                self._send_json(503, {"ok": False})
            return
        if path == "/notify":
            title = (data.get("title") or "KodiCord").strip()
            message = (data.get("message") or "").strip()
            try:
                _notify_tray(title, message)
                self._send_json(200, {"ok": True})
            except Exception as e:
                print("[bridge] notify failed: %s" % e)
                self._send_json(503, {"ok": False})
            return
        self._send_json(404, {"ok": False})

    def log_message(self, *args):
        # keep console quiet
        pass


# ---------------------------------------------------------------------------
# System tray (notification area) icon for Windows.
# ---------------------------------------------------------------------------
_TRAY_ICON_B64 = "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"

_TRAY_ICON_PATH = None


def _tray_icon_path():
    global _TRAY_ICON_PATH
    if _TRAY_ICON_PATH and os.path.exists(_TRAY_ICON_PATH):
        return _TRAY_ICON_PATH
    data = base64.b64decode(_TRAY_ICON_B64)
    # Save the icon next to the bridge with a proper, stable name/location.
    preferred = os.path.join(HERE, "kodicord_tray.ico")
    try:
        if not os.path.exists(preferred):
            with open(preferred, "wb") as f:
                f.write(data)
        _TRAY_ICON_PATH = preferred
        return preferred
    except Exception:
        fd, path = tempfile.mkstemp(suffix=".ico", prefix="kodicord_tray_")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        _TRAY_ICON_PATH = path
        return path



def _tray_icon_mono_path():
    preferred = os.path.join(HERE, "kodicord_tray_monochrome.ico")
    if os.path.exists(preferred):
        return preferred
    try:
        from PIL import Image
        img = Image.open(os.path.join(HERE, "kodicord_tray.ico")).convert("RGBA")
        g = img.convert("L")
        # rebuild RGBA with grayscale RGB
        arr = np.array(img) if False else None
        import numpy as np
        a = np.array(img)
        gray = np.array(g)
        a[:, :, 0] = gray
        a[:, :, 1] = gray
        a[:, :, 2] = gray
        out = Image.fromarray(a, "RGBA")
        out.save(preferred, format="ICO", sizes=[(16,16),(32,32),(48,48),(256,256)])
        return preferred
    except Exception:
        return os.path.join(HERE, "kodicord_tray.ico")



def _restart_discord():
    global STATE, _TRAY_INSTANCE
    if STATE is None:
        return
    try:
        with STATE.lock:
            if STATE.ipc is not None:
                try:
                    STATE.ipc.close()
                except Exception:
                    pass
            STATE.ipc = None
        msg = "Discord connection restarted. It will only grab new info when the next video/song etc plays."
        print("[bridge] " + msg)
        # Show popup on both platforms
        try:
            t = _TRAY_INSTANCE
            if t is not None:
                if hasattr(t, "_tray"):  # Qt
                    try:
                        from PyQt6 import QtWidgets
                        icon = QtWidgets.QSystemTrayIcon.MessageIcon.Information
                    except Exception:
                        try:
                            from PyQt5 import QtWidgets
                            icon = QtWidgets.QSystemTrayIcon.MessageIcon.Information
                        except Exception:
                            icon = None
                    if icon is not None:
                        t._tray.showMessage("KodiCord bridge", msg, icon, 4000)
                elif hasattr(t, "_nid"):  # Windows
                    import ctypes
                    nid = t._nid
                    nid.uFlags = 0x01 | 0x02 | 0x04 | 0x10
                    nid.szInfo = msg[:255]
                    nid.szInfoTitle = "KodiCord bridge"
                    nid.dwInfoFlags = 0x01
                    t._shell32.Shell_NotifyIconW(0x01, ctypes.byref(nid))
                    nid.uFlags = 0x01 | 0x02 | 0x04
                    nid.szInfo = ""
        except Exception:
            pass
    except Exception as e:
        print("[bridge] restart failed: %s" % e)



def _notify_tray(title, message):
    global _TRAY_INSTANCE
    t = _TRAY_INSTANCE
    if t is None:
        return
    try:
        if hasattr(t, "_tray"):  # Qt
            try:
                from PyQt6 import QtWidgets
                icon = QtWidgets.QSystemTrayIcon.MessageIcon.Information
            except Exception:
                try:
                    from PyQt5 import QtWidgets
                    icon = QtWidgets.QSystemTrayIcon.MessageIcon.Information
                except Exception:
                    icon = None
            if icon is not None:
                t._tray.showMessage(str(title)[:63], str(message)[:255], icon, 4000)
            return
        if hasattr(t, "_nid"):  # Windows
            import ctypes
            nid = t._nid
            nid.uFlags = 0x01 | 0x02 | 0x04 | 0x10
            nid.szInfo = str(message)[:255]
            nid.szInfoTitle = str(title)[:63]
            nid.dwInfoFlags = 0x01
            t._shell32.Shell_NotifyIconW(0x01, ctypes.byref(nid))  # NIM_MODIFY
            # reset
            nid.uFlags = 0x01 | 0x02 | 0x04
            nid.szInfo = ""
            return
        # pystray
        if hasattr(t, "notify"):
            try:
                t.notify(str(message), str(title))
            except Exception:
                try:
                    t.notify(str(message))
                except Exception:
                    pass
            return
    except Exception:
        pass


def _status_text():
    try:
        if STATE is None:
            return "Bridge not initialized"
        ok = STATE.ensure()
        return "Discord: %s" % ("connected" if ok else "disconnected")
    except Exception as e:
        return "Status error: %s" % e

# ---------------------------------------------------------------------------
# Launch at startup (autostart) helpers - cross-platform (Windows + Linux).
# ---------------------------------------------------------------------------

AUTOSTART_NAME = "KodiCordBridge"


def _autostart_command():
    args = [sys.executable, os.path.abspath(__file__)] + list(sys.argv[1:])
    if sys.platform == "win32":
        import subprocess
        return subprocess.list2cmdline(args)
    import shlex
    return shlex.join(args)


def _linux_autostart_dir(override=None):
    if override is not None:
        return override
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "autostart")


def _linux_desktop_path(autostart_dir=None):
    return os.path.join(_linux_autostart_dir(autostart_dir), "kodicord-bridge.desktop")


def _linux_autostart_enabled(autostart_dir=None):
    return os.path.exists(_linux_desktop_path(autostart_dir))


def _linux_enable_autostart(autostart_dir=None):
    d = _linux_autostart_dir(autostart_dir)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return False
    path = os.path.join(d, "kodicord-bridge.desktop")
    try:
        with open(path, "w") as f:
            f.write("[Desktop Entry]\n")
            f.write("Type=Application\n")
            f.write("Name=KodiCord Bridge\n")
            f.write("Comment=KodiCord Discord Rich Presence bridge\n")
            f.write("Exec=%s\n" % _autostart_command())
            f.write("Terminal=false\n")
            f.write("X-GNOME-Autostart-enabled=true\n")
        return True
    except Exception:
        return False


def _linux_disable_autostart(autostart_dir=None):
    path = _linux_desktop_path(autostart_dir)
    try:
        if os.path.exists(path):
            os.remove(path)
        return True
    except Exception:
        return False


def _windows_autostart_enabled():
    if winreg is None:
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_READ)
        try:
            val, _ = winreg.QueryValueEx(key, AUTOSTART_NAME)
            return bool(val)
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def _windows_enable_autostart():
    if winreg is None:
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE)
        try:
            winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ,
                              _autostart_command())
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _windows_disable_autostart():
    if winreg is None:
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                            winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(key, AUTOSTART_NAME)
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return True


def _mac_autostart_path():
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents",
                        "com.kodicord.bridge.plist")


def _mac_autostart_enabled():
    return os.path.exists(_mac_autostart_path())


def _mac_enable_autostart():
    try:
        import plistlib
        path = _mac_autostart_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        plist = {
            "Label": "com.kodicord.bridge",
            "ProgramArguments": [sys.executable, os.path.abspath(__file__)] + list(sys.argv[1:]),
            "RunAtLoad": True,
        }
        with open(path, "wb") as f:
            plistlib.dump(plist, f)
        return True
    except Exception:
        return False


def _mac_disable_autostart():
    path = _mac_autostart_path()
    try:
        if os.path.exists(path):
            os.remove(path)
        return True
    except Exception:
        return False


def autostart_enabled():
    if sys.platform == "win32":
        return _windows_autostart_enabled()
    if sys.platform.startswith("linux"):
        return _linux_autostart_enabled()
    if sys.platform == "darwin":
        return _mac_autostart_enabled()
    return False


def enable_autostart(autostart_dir=None):
    if sys.platform == "win32":
        return _windows_enable_autostart()
    if sys.platform.startswith("linux"):
        return _linux_enable_autostart(autostart_dir)
    if sys.platform == "darwin":
        return _mac_enable_autostart()
    return False


def disable_autostart(autostart_dir=None):
    if sys.platform == "win32":
        return _windows_disable_autostart()
    if sys.platform.startswith("linux"):
        return _linux_disable_autostart(autostart_dir)
    if sys.platform == "darwin":
        return _mac_disable_autostart()
    return False


def toggle_autostart(autostart_dir=None):
    if autostart_enabled():
        disable_autostart(autostart_dir)
    else:
        enable_autostart(autostart_dir)
    return autostart_enabled()

class WindowsTray:
    def __init__(self, tooltip="KodiCord bridge", on_exit=None):
        self.tooltip = tooltip
        self.on_exit = on_exit
        self.monotone = False
        self._stop = threading.Event()

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            import ctypes
            from ctypes import wintypes
        except Exception:
            return

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32

        icon_path = _tray_icon_path()

        WM_TRAYICON = 0x0400 + 1
        WM_COMMAND = 0x0111
        WM_DESTROY = 0x0002
        WM_RBUTTONUP = 0x0205
        WM_LBUTTONDBLCLK = 0x0203

        NIM_ADD = 0x00
        NIM_DELETE = 0x02
        NIF_MESSAGE = 0x01
        NIF_ICON = 0x02
        NIF_TIP = 0x04

        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        LR_DEFAULTSIZE = 0x00000040

        hicon = user32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0,
                                  LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if not hicon:
            hicon = user32.LoadIconW(None, 32512)  # IDI_APPLICATION

        WndProcType = ctypes.WINFUNCTYPE(wintypes.LRESULT, wintypes.HWND,
                                        wintypes.UINT, wintypes.WPARAM,
                                        wintypes.LPARAM)

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("style", wintypes.UINT),
                ("lpfnWndProc", WndProcType),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HCURSOR),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm", wintypes.HICON),
            ]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", wintypes.HICON),
            ]

        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", POINT),
            ]

        hinst = kernel32.GetModuleHandleW(None)
        class_name = "KodiCordBridgeTray"

        self._hwnd = None
        nid = NOTIFYICONDATAW()

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_TRAYICON:
                if lparam == WM_RBUTTONUP:
                    self._show_menu(hwnd, user32)
                return 0
            if msg == WM_COMMAND:
                cmd = wparam & 0xFFFF
                if cmd == 1001:
                    user32.PostQuitMessage(0)
                elif cmd == 2001:
                    self._toggle_monotone(hwnd, user32)
                elif cmd == 2002:
                    _restart_discord()
                elif cmd == 2003:
                    self._show_status(hwnd, user32)
                elif cmd == 2004:
                    toggle_autostart()
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wndproc_cb = WndProcType(wndproc)
        # keep reference alive
        self._wndproc_cb = wndproc_cb

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = wndproc_cb
        wc.hInstance = hinst
        wc.lpszClassName = class_name
        wc.hIcon = hicon
        wc.hIconSm = hicon
        user32.RegisterClassExW(ctypes.byref(wc))

        hwnd = user32.CreateWindowExW(0, class_name, "KodiCord Bridge", 0,
                                      0, 0, 0, 0, None, None, hinst, None)
        self._hwnd = hwnd

        self._nid = nid
        self._shell32 = shell32
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = hicon
        nid.szTip = self.tooltip[:127]
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

        # message loop
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # cleanup
        shell32.Shell_NotifyIconW(0x02, ctypes.byref(nid))  # NIM_DELETE
        user32.DestroyWindow(hwnd)

        if self.on_exit is not None:
            try:
                self.on_exit()
            except Exception:
                pass

    def _toggle_monotone(self, hwnd, user32, shell32, nid):
        self.monotone = not self.monotone
        path = _tray_icon_mono_path() if self.monotone else _tray_icon_path()
        hicon = user32.LoadImageW(None, path, 1, 0, 0, 0x00000010 | 0x00000040)
        if hicon:
            self._nid.hIcon = hicon
            self._shell32.Shell_NotifyIconW(0x01, ctypes.byref(self._nid))  # NIM_MODIFY

    def _show_status(self, hwnd, user32):
        text = _status_text()
        nid = self._nid
        nid.uFlags = 0x01 | 0x02 | 0x04 | 0x10  # NIF_MESSAGE|ICON|TIP|INFO
        nid.szInfo = text[:255]
        nid.szInfoTitle = "KodiCord bridge"
        nid.dwInfoFlags = 0x01  # NIIF_INFO
        self._shell32.Shell_NotifyIconW(0x01, ctypes.byref(nid))  # NIM_MODIFY
        # reset flags
        nid.uFlags = 0x01 | 0x02 | 0x04
        nid.szInfo = ""

    def _show_menu(self, hwnd, user32):
        # need shell32/nid access; stored on self during run
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, 0, 2001, "Monochrome icon" if not self.monotone else "Color icon")
        user32.AppendMenuW(menu, 0, 2002, "Restart Discord connection")
        user32.AppendMenuW(menu, 0, 2003, "Show status")
        flags = 0x0008 if autostart_enabled() else 0
        user32.AppendMenuW(menu, flags, 2004, "Launch at startup")
        user32.AppendMenuW(menu, 0, 1001, "Exit KodiCord bridge")
        pt = None
        from ctypes import wintypes as _w
        p = _w.POINT()
        user32.GetCursorPos(ctypes.byref(p))
        user32.SetForegroundWindow(hwnd)
        user32.TrackPopupMenu(menu, 0, p.x, p.y, 0, hwnd, None)
        user32.PostMessageW(hwnd, 0, 0, 0)
        user32.DestroyMenu(menu)



class QtTray:
    """System tray icon using PyQt (Linux/macOS/Windows fallback)."""
    def __init__(self, tooltip="KodiCord bridge", on_exit=None):
        self.tooltip = tooltip
        self.on_exit = on_exit

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        # Try PyQt6 then PyQt5
        app_mod = None
        for modname in ("PyQt6", "PyQt5"):
            try:
                if modname == "PyQt6":
                    from PyQt6 import QtWidgets, QtGui, QtCore
                else:
                    from PyQt5 import QtWidgets, QtGui, QtCore
                app_mod = (QtWidgets, QtGui, QtCore, modname)
                break
            except Exception:
                continue
        if app_mod is None:
            return
        QtWidgets, QtGui, QtCore, modname = app_mod
        try:
            icon_path = _tray_icon_path()
        except Exception:
            icon_path = None

        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication([])

        tray = QtWidgets.QSystemTrayIcon()
        if icon_path:
            tray.setIcon(QtGui.QIcon(icon_path))
        tray.setToolTip(self.tooltip)

        self._tray = tray
        self.monotone = False
        menu = QtWidgets.QMenu()
        self._mono_action = menu.addAction("Monochrome icon")
        restart_action = menu.addAction("Restart Discord connection")
        status_action = menu.addAction("Show status")
        self._launch_action = menu.addAction("Launch at startup")
        self._launch_action.setCheckable(True)
        self._launch_action.setChecked(autostart_enabled())
        exit_action = menu.addAction("Exit KodiCord bridge")
        def _toggle():
            self.monotone = not self.monotone
            path = _tray_icon_mono_path() if self.monotone else _tray_icon_path()
            self._tray.setIcon(QtGui.QIcon(path))
            self._mono_action.setText("Color icon" if self.monotone else "Monochrome icon")
        self._mono_action.triggered.connect(_toggle)
        restart_action.triggered.connect(_restart_discord)
        status_action.triggered.connect(lambda: self._tray.showMessage("KodiCord bridge", _status_text(), QtWidgets.QSystemTrayIcon.MessageIcon.Information, 3000))
        def _toggle_launch(checked):
            if checked:
                enable_autostart()
            else:
                disable_autostart()
            self._launch_action.setChecked(autostart_enabled())
        self._launch_action.toggled.connect(_toggle_launch)
        def _exit():
            tray.hide()
            if self.on_exit is not None:
                try:
                    self.on_exit()
                except Exception:
                    pass
            app.quit()
        exit_action.triggered.connect(_exit)
        tray.setContextMenu(menu)
        tray.show()

        # Optional: show a balloon on start
        try:
            tray.showMessage("KodiCord", "Bridge is running in the system tray.",
                             QtWidgets.QSystemTrayIcon.MessageIcon.Information, 3000)
        except Exception:
            pass

        app.exec() if hasattr(app, "exec") else app.exec_()


def _try_pystray(on_exit=None, tooltip="KodiCord bridge running"):
    try:
        import pystray
        from PIL import Image
        import io
    except Exception:
        return None
    try:
        data = base64.b64decode(_TRAY_ICON_B64)
        img = Image.open(io.BytesIO(data))
    except Exception:
        return None

    def on_exit_cb(icon, item):
        icon.stop()
        if on_exit is not None:
            try:
                on_exit()
            except Exception:
                pass

    def _toggle_launch(icon, item):
        toggle_autostart()
    menu = pystray.Menu(
        pystray.MenuItem("Launch at startup", _toggle_launch, checked=lambda item: autostart_enabled()),
        pystray.MenuItem("Exit KodiCord bridge", on_exit_cb),
    )
    icon = pystray.Icon("KodiCordBridge", img, tooltip, menu)
    t = threading.Thread(target=icon.run, daemon=True)
    t.start()
    # store to avoid gc
    _try_pystray._icon = icon
    return icon



def _start_tray(on_exit=None):
    global _TRAY_INSTANCE
    tooltip = "KodiCord bridge running"
    # Prefer a cross-platform backend when available.
    if sys.platform != "win32":
        # Try pystray first (works on X11/AppIndicator setups).
        icon = _try_pystray(on_exit=on_exit, tooltip=tooltip)
        if icon is not None:
            _TRAY_INSTANCE = icon
            return icon
        # Fall back to PyQt tray icon.
        try:
            import PyQt6  # noqa: F401
            _ = PyQt6
        except Exception:
            try:
                import PyQt5  # noqa: F401
                _ = PyQt5
            except Exception:
                return None
        tray = QtTray(tooltip=tooltip, on_exit=on_exit)
        tray.start()
        _TRAY_INSTANCE = tray
        return tray
    tray = WindowsTray(tooltip=tooltip, on_exit=on_exit)
    tray.start()
    _TRAY_INSTANCE = tray
    return tray


def main():
    global STATE
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", default="")
    args = ap.parse_args()

    STATE = BridgeState(args.client_id, args.token)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)

    def _shutdown():
        try:
            httpd.shutdown()
        except Exception:
            pass

    tray = _start_tray(on_exit=_shutdown)

    print("KodiCord bridge listening on %s:%d" % (args.host, args.port))
    if tray is not None:
        print("KodiCord bridge running in the system tray (notification area).")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if STATE.ipc is not None:
                STATE.ipc.close()
        except Exception:
            pass
        httpd.server_close()
        if tray is not None:
            try:
                # ensure tray thread exits
                pass
            except Exception:
                pass


if __name__ == "__main__":
    main()
