"""Native settings adapters. No account tokens are transferred."""
from pathlib import Path
import os
import sys
import xml.etree.ElementTree as ET
import psutil

IDENTITY = ("MachineIdentifier", "ProcessedMachineIdentifier", "AnonymousMachineIdentifier")
PORTABLE = (*IDENTITY, "FriendlyName")
SAFE = {"autoEmptyTrash": "0", "FSEventLibraryUpdatesEnabled": "0",
        "FSEventLibraryPartialScanEnabled": "0", "ScheduledLibraryUpdatesEnabled": "0"}
REGKEY = r"Software\Plex, Inc.\Plex Media Server"


def host_os():
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    raise RuntimeError("This release supports Windows and Linux only.")


def default_data():
    if host_os() == "windows":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGKEY) as key:
                base = winreg.QueryValueEx(key, "LocalAppDataPath")[0]
                return Path(base) / "Plex Media Server"
        except FileNotFoundError:
            return Path(os.environ["LOCALAPPDATA"]) / "Plex Media Server"
    return Path("/var/lib/plexmediaserver/Library/Application Support/Plex Media Server")


class PlexRunningError(RuntimeError):
    """Plex or one of its helpers is still running."""


def ensure_stopped():
    """Fail closed if a Plex process is running or cannot be inspected."""
    for process in psutil.process_iter():
        try:
            name = process.name().lower()
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise RuntimeError("Cannot inspect running processes. Use an account with permission to inspect Plex.") from exc
        if name.startswith(("plex media server", "plex media scanner", "plex transcoder", "plex tuner service")):
            raise PlexRunningError("Plex is running. Stop Plex and disable automatic restart before continuing.")


def read_settings(data):
    if host_os() == "windows":
        import winreg
        result = {}
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGKEY) as key:
            for name in PORTABLE:
                try:
                    result[name] = str(winreg.QueryValueEx(key, name)[0])
                except FileNotFoundError:
                    pass
        return result
    root = ET.parse(Path(data) / "Preferences.xml").getroot()
    return {k: root.attrib[k] for k in PORTABLE if k in root.attrib}


def validate_settings(settings):
    if not isinstance(settings, dict) or set(settings) - set(PORTABLE):
        raise ValueError("Backup contains unsupported settings.")
    if any(not isinstance(v, str) or len(v) > 4096 for v in settings.values()):
        raise ValueError("Invalid settings values.")
    if any(not settings.get(k) for k in IDENTITY):
        raise ValueError("All three Plex identity values are required. Select the correct Plex data/account.")


def write_linux_settings(stage, existing, settings):
    old = Path(existing) / "Preferences.xml"
    root = ET.parse(old).getroot() if old.exists() else ET.Element("Preferences")
    # A fresh destination may have been claimed under a different server identity.
    for key in ("PlexOnlineToken", "PlexOnlineUsername", "PlexOnlineMail", "PlexOnlineHome"):
        root.attrib.pop(key, None)
    root.attrib.update(settings)
    root.attrib.update(SAFE)
    ET.ElementTree(root).write(Path(stage) / "Preferences.xml", encoding="utf-8", xml_declaration=True)
    (Path(stage) / "Preferences.xml").chmod(0o600)


def registry_snapshot():
    import winreg
    result = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGKEY) as key:
        for name in (*PORTABLE, *SAFE, "PlexOnlineToken", "PlexOnlineUsername", "PlexOnlineMail", "PlexOnlineHome"):
            try:
                value, kind = winreg.QueryValueEx(key, name)
                result[name] = [value, kind]
            except FileNotFoundError:
                result[name] = None
    return result


def registry_restore(snapshot):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGKEY) as key:
        for name, entry in snapshot.items():
            if entry is None:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, name, 0, entry[1], entry[0])


def write_windows_settings(settings):
    import winreg
    values = {k: [v, winreg.REG_SZ] for k, v in settings.items()}
    values.update({k: [0, winreg.REG_DWORD] for k in SAFE})
    values.update({k: None for k in ("PlexOnlineToken", "PlexOnlineUsername", "PlexOnlineMail", "PlexOnlineHome")})
    registry_restore(values)


def owner_ids(owner):
    if host_os() != "linux":
        return None
    import pwd
    import grp
    user, group = owner.split(":", 1)
    return pwd.getpwnam(user).pw_uid, grp.getgrnam(group).gr_gid


def apply_owner(path, ids):
    if ids is None:
        return
    uid, gid = ids
    for base, dirs, files in os.walk(path):
        os.chown(base, uid, gid)
        os.chmod(base, 0o750)
        for name in files:
            item = Path(base) / name
            os.chown(item, uid, gid)
            os.chmod(item, 0o640)
    preferences = Path(path) / "Preferences.xml"
    if preferences.exists():
        preferences.chmod(0o600)
