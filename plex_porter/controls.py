"""Open Plex locally and request a normal shutdown of the native server."""
import os
from pathlib import Path
import subprocess
import time
import psutil
from . import platforms
from .installer import external_environment

PLEX_URL = "http://127.0.0.1:32400/web"


def open_plex():
    if platforms.host_os() == "windows":
        os.startfile(PLEX_URL)
    else:
        env = external_environment()
        command = ["/usr/bin/xdg-open", PLEX_URL]
        if os.geteuid() == 0:
            # The .deb menu runs with pkexec. Open the browser as the desktop user,
            # never as root, and reconnect to that user's session bus.
            import pwd
            uid = int(os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID") or "0")
            if uid <= 0:
                raise RuntimeError(f"Open {PLEX_URL} in your desktop browser. No original desktop user was found.")
            user = pwd.getpwuid(uid)
            runtime = f"/run/user/{uid}"
            command = ["/usr/sbin/runuser", "-u", user.pw_name, "--", "/usr/bin/env",
                       f"HOME={user.pw_dir}", f"USER={user.pw_name}", f"LOGNAME={user.pw_name}",
                       f"XDG_RUNTIME_DIR={runtime}", f"DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus",
                       "/usr/bin/xdg-open", PLEX_URL]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f"Could not open the default browser. Open {PLEX_URL} manually.")
    return f"Opened {PLEX_URL} in your default browser. Plex must be running to load the page."


def shutdown_plex(progress=lambda message: None, timeout=60):
    try:
        platforms.ensure_stopped()
    except RuntimeError:
        pass
    else:
        return "Plex is already stopped. You can export or import."
    env = external_environment()
    progress("Requesting Plex shutdown… current streams will disconnect.")
    if platforms.host_os() == "linux":
        command = ["/usr/bin/systemctl", "stop", "--no-block", "plexmediaserver.service"]
        if os.geteuid() != 0:
            command.insert(0, "/usr/bin/pkexec")
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError("Could not stop the native Plex service: " + (result.stderr.strip() or result.stdout.strip()))
    else:
        pids = []
        for process in psutil.process_iter():
            try:
                if process.name().lower() == "plex media server.exe":
                    pids.append(process.pid)
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied as error:
                raise RuntimeError("Cannot inspect Plex. Run under the Windows account that runs Plex.") from error
        if not pids:
            raise RuntimeError("Plex helper processes are still running. Close Plex or stop its custom Windows service.")
        for pid in pids:
            # Without /F, taskkill requests a normal application close (WM_CLOSE).
            # Never force-kill a server while its database may be writing.
            result = subprocess.run(["taskkill.exe", "/PID", str(pid)], env=env, capture_output=True,
                                    text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                try:
                    platforms.ensure_stopped()
                except RuntimeError:
                    raise RuntimeError("Plex did not accept a normal shutdown. Exit its tray icon or stop its custom service. " + result.stdout.strip())
    deadline = time.monotonic() + timeout
    while True:
        try:
            platforms.ensure_stopped()
        except RuntimeError as error:
            if time.monotonic() >= deadline:
                raise RuntimeError("Plex has not fully stopped. No backup/import was started. " + str(error)) from error
            progress("Waiting for Plex and its helper processes to exit…")
            time.sleep(0.5)
        else:
            return "Plex is stopped. You can now export or import."
