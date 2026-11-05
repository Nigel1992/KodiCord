import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "companion"))
import discord_bridge as bridge


def test_linux_enable_disable(tmp_path):
    d = tmp_path / "autostart"
    assert not bridge._linux_autostart_enabled(str(d))
    assert bridge._linux_enable_autostart(str(d)) is True
    assert bridge._linux_autostart_enabled(str(d)) is True
    desktop = d / "kodicord-bridge.desktop"
    content = desktop.read_text()
    assert "Exec=" in content
    assert bridge._linux_disable_autostart(str(d)) is True
    assert not bridge._linux_autostart_enabled(str(d))
    assert not desktop.exists()


def test_linux_autostart_dir_default(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    d = bridge._linux_autostart_dir()
    assert d == str(tmp_path / "cfg" / "autostart")


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 3

    def __init__(self):
        self.store = {}

    def OpenKey(self, root, path, reserved, access):
        return (root, path)

    def QueryValueEx(self, key, name):
        root, path = key
        full = (root, path, name)
        if full not in self.store:
            raise FileNotFoundError(name)
        return (self.store[full], 0)

    def SetValueEx(self, key, name, reserved, typ, value):
        root, path = key
        self.store[(root, path, name)] = value

    def DeleteValue(self, key, name):
        root, path = key
        full = (root, path, name)
        if full not in self.store:
            raise FileNotFoundError(name)
        del self.store[full]

    def CloseKey(self, key):
        pass


def test_windows_autostart(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setattr(bridge, "winreg", fake)
    monkeypatch.setattr(bridge.sys, "platform", "win32")
    assert bridge.autostart_enabled() is False
    assert bridge.enable_autostart() is True
    assert bridge.autostart_enabled() is True
    assert bridge.disable_autostart() is True
    assert bridge.autostart_enabled() is False
    assert bridge.disable_autostart() is True


def test_toggle_autostart_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge.sys, "platform", "linux")
    d = tmp_path / "autostart"
    if (d / "kodicord-bridge.desktop").exists():
        (d / "kodicord-bridge.desktop").unlink()
    assert bridge._linux_autostart_enabled(str(d)) is False
    bridge._linux_enable_autostart(str(d))
    assert bridge._linux_autostart_enabled(str(d)) is True
    bridge._linux_disable_autostart(str(d))
    assert bridge._linux_autostart_enabled(str(d)) is False


def test_autostart_command_contains_script():
    cmd = bridge._autostart_command()
    assert "discord_bridge.py" in cmd
