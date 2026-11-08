"""Package an onedir PyInstaller build. Run on Ubuntu with dpkg-deb installed."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("bundle", type=Path)
parser.add_argument("--output", type=Path, default=Path("dist"))
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
version = "0.5.0"
args.output.mkdir(parents=True, exist_ok=True)
output = args.output.resolve() / f"plex-porter_{version}_amd64.deb"
if not (args.bundle / "PlexPorter").is_file():
    parser.error("Bundle must contain the frozen PlexPorter executable")
with tempfile.TemporaryDirectory(prefix="plex-deb-") as temporary:
    stage = Path(temporary)
    app = stage / "opt/plex-porter"
    shutil.copytree(args.bundle, app)
    (app / "PlexPorter").chmod(0o755)
    def write(name, content, mode=0o644):
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(mode)
    size = sum(p.stat().st_size for p in app.rglob("*") if p.is_file()) // 1024
    write("DEBIAN/control", f"""Package: plex-porter
Version: {version}
Section: utils
Priority: optional
Architecture: amd64
Maintainer: Plex Porter contributors <maintainers@users.noreply.github.com>
Installed-Size: {size}
Depends: libc6 (>= 2.35), libfontconfig1, fontconfig-config, fonts-dejavu-core, policykit-1, xdg-utils, util-linux
Description: Move Plex library data between Windows and Linux
 Includes Python, Tk and application dependencies. Exports and imports
 library databases, artwork and server identity. Never backs up movies
 or music. Plex Media Server can be installed using the in-app button.
""")
    write("usr/bin/plex-porter", '#!/bin/sh\nexec /opt/plex-porter/PlexPorter "$@"\n', 0o755)
    write("usr/share/applications/plex-porter.desktop", """[Desktop Entry]
Type=Application
Name=Plex Porter
Comment=Export and import Plex libraries between Windows and Linux
Exec=pkexec /opt/plex-porter/PlexPorter
Icon=plex-porter
Terminal=false
Categories=Utility;
StartupNotify=true
""")
    write("usr/share/polkit-1/actions/org.plexporter.manage.policy", """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN" "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <vendor>Plex Porter contributors</vendor>
  <action id="org.plexporter.manage">
    <description>Manage Plex library backups</description>
    <message>Administrator permission is required to access Plex server data.</message>
    <defaults><allow_any>no</allow_any><allow_inactive>no</allow_inactive><allow_active>auth_admin</allow_active></defaults>
    <annotate key="org.freedesktop.policykit.exec.path">/opt/plex-porter/PlexPorter</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">true</annotate>
  </action>
</policyconfig>
""")
    write("usr/share/icons/hicolor/scalable/apps/plex-porter.svg", (root / "packaging/plex-porter.svg").read_text())
    write("usr/share/doc/plex-porter/copyright", (root / "LICENSE").read_text())
    write("usr/share/doc/plex-porter/README.md", (root / "README.md").read_text())
    subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(output)], check=True)
print(output)
