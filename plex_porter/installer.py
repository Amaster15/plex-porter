"""Fetch the current official Plex installer; never redistribute Plex itself."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from urllib.parse import urlparse
import certifi
from .platforms import host_os

API = "https://plex.tv/api/downloads/5.json"
HOSTS = {"plex.tv", "www.plex.tv", "downloads.plex.tv"}


def valid_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Installer URL is not an official Plex HTTPS download.")
    return url


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        valid_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_official(url):
    opener = urllib.request.build_opener(OfficialRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
    return opener.open(urllib.request.Request(valid_url(url), headers={"User-Agent": "PlexPorter/0.2"}), timeout=60)


def choose_release(metadata, system, machine):
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(machine.lower())
    if not arch or (system == "windows" and arch != "x86_64"):
        raise ValueError("No supported Plex installer for this processor.")
    platform_key = "Windows" if system == "windows" else "Linux"
    distro = "windows" if system == "windows" else "debian"
    build = system + "-" + arch
    for item in metadata["computer"][platform_key]["releases"]:
        if item.get("build") == build and item.get("distro") == distro:
            valid_url(item["url"])
            if urlparse(item["url"]).hostname != "downloads.plex.tv":
                raise ValueError("Unexpected Plex download host.")
            if not re.fullmatch(r"[0-9a-fA-F]{40}", item.get("checksum", "")):
                raise ValueError("Plex did not supply a valid installer checksum.")
            return item
    raise ValueError("Plex has no matching installer in its current release feed.")


def external_environment():
    env = os.environ.copy()
    # Frozen applications alter library lookup; never pass bundled libraries to apt/PowerShell.
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


def install_plex(progress=lambda message: None):
    system = host_os()
    if system == "linux" and not Path("/usr/bin/apt-get").exists():
        raise RuntimeError("The Linux Install Plex button supports Xubuntu/Ubuntu/Debian (apt).")
    progress("Finding the current official Plex Media Server installer…")
    with open_official(API) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("Plex release metadata is too large.")
        release = choose_release(json.loads(raw), system, platform.machine())
    folder = Path(tempfile.mkdtemp(prefix="plex-porter-installer-"))
    package = folder / ("PlexMediaServer.exe" if system == "windows" else "plexmediaserver.deb")
    try:
        digest = hashlib.sha1()  # Matches Plex's published download checksum; TLS authenticates the feed.
        size = 0
        with open_official(release["url"]) as response, package.open("xb") as output:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 1024 * 1024 * 1024:
                    raise ValueError("Installer exceeds the 1 GiB download limit.")
                output.write(chunk)
                digest.update(chunk)
                progress(f"Downloading Plex Media Server… {size // (1024 * 1024)} MB")
        if digest.hexdigest().lower() != release["checksum"].lower():
            raise ValueError("Installer checksum failed. Nothing was installed.")
        env = external_environment()
        if system == "windows":
            env["PLEX_PORTER_INSTALLER"] = str(package)
            script = "$s=Get-AuthenticodeSignature -LiteralPath $env:PLEX_PORTER_INSTALLER; if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Plex'){exit 1}"
            # Reset the Windows DLL directory before launching system tools.
            if getattr(sys, "frozen", False):
                import ctypes
                ctypes.windll.kernel32.SetDllDirectoryW(None)
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], env=env,
                           check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            progress("Opening the signed Plex installer. Follow its setup window.")
            result = subprocess.run([str(package)], env=env)
            if result.returncode not in (0, 3010):
                raise RuntimeError(f"Plex installer exited with code {result.returncode}.")
        else:
            command = ["/usr/bin/apt-get", "install", "-y", str(package)]
            if os.geteuid() != 0:
                command.insert(0, "/usr/bin/pkexec")
            progress("Installing Plex. Approve the system administrator prompt if shown…")
            result = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if result.returncode:
                raise RuntimeError("Plex installation did not complete:\n" + result.stdout[-2500:])
        return "Plex installer finished. Open Plex once to initialize it, then close/stop Plex before importing your backup."
    finally:
        shutil.rmtree(folder, ignore_errors=True)
