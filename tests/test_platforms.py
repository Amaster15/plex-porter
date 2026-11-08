"""Exercise adapters without modifying the host's real registry or processes."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import unittest
import xml.etree.ElementTree as ET
from plex_porter import platforms


class FakeRegistry:
    HKEY_CURRENT_USER = 1
    REG_SZ = 1
    REG_DWORD = 4

    def __init__(self):
        self.values = {}

    @contextmanager
    def OpenKey(self, *_):
        yield self

    CreateKey = OpenKey

    def QueryValueEx(self, _, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name]

    def SetValueEx(self, _, name, reserved, kind, value):
        self.values[name] = (value, kind)

    def DeleteValue(self, _, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


class PlatformTests(unittest.TestCase):
    def test_windows_settings_translate_and_rollback_with_types(self):
        reg = FakeRegistry()
        reg.values = {"MachineIdentifier": ("old", 1), "PlexOnlineToken": ("private", 1),
                      "autoEmptyTrash": (1, 4), "LocalAppDataPath": (r"D:\Plex", 1)}
        before = dict(reg.values)
        settings = {name: f"new-{name}" for name in platforms.IDENTITY}
        with patch.dict("sys.modules", {"winreg": reg}):
            snapshot = platforms.registry_snapshot()
            platforms.write_windows_settings(settings)
            self.assertEqual(reg.values["autoEmptyTrash"], (0, 4))
            self.assertNotIn("PlexOnlineToken", reg.values)
            self.assertEqual(reg.values["MachineIdentifier"], (settings["MachineIdentifier"], 1))
            platforms.registry_restore(snapshot)
        self.assertEqual(reg.values, before)

    def test_read_windows_settings_excludes_account_token(self):
        reg = FakeRegistry()
        reg.values = {name: (name, 1) for name in platforms.IDENTITY}
        reg.values["PlexOnlineToken"] = ("private", 1)
        with patch.dict("sys.modules", {"winreg": reg}), patch.object(platforms, "host_os", return_value="windows"):
            settings = platforms.read_settings(Path("unused"))
        self.assertEqual(set(settings), set(platforms.IDENTITY))

    def test_xml_escapes_server_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage, existing = Path(tmp) / "stage", Path(tmp) / "old"
            stage.mkdir()
            existing.mkdir()
            platforms.write_linux_settings(stage, existing, {"FriendlyName": 'Movies & "Music" <3'})
            root = ET.parse(stage / "Preferences.xml").getroot()
            self.assertEqual(root.get("FriendlyName"), 'Movies & "Music" <3')
            self.assertEqual(root.get("autoEmptyTrash"), "0")

    def test_running_plex_is_blocked(self):
        for name in ["Plex Media Server", "Plex Media Server.exe", "Plex Media Scanner.exe", "Plex Transcoder"]:
            process = SimpleNamespace(name=lambda: name)
            with patch.object(platforms.psutil, "process_iter", return_value=[process]), self.assertRaises(RuntimeError):
                platforms.ensure_stopped()

    def test_uninspectable_process_fails_closed(self):
        def denied():
            raise platforms.psutil.AccessDenied(123)
        with patch.object(platforms.psutil, "process_iter", return_value=[SimpleNamespace(name=denied)]):
            with self.assertRaisesRegex(RuntimeError, "Cannot inspect"):
                platforms.ensure_stopped()

    def test_exited_process_does_not_block(self):
        def gone():
            raise platforms.psutil.NoSuchProcess(123)
        with patch.object(platforms.psutil, "process_iter", return_value=[SimpleNamespace(name=gone)]):
            platforms.ensure_stopped()
