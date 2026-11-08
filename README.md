# Plex Porter

A small desktop app for moving a Plex Media Server library between **Windows and Linux**.

Main actions: **Export**, **Import**, and **Install Plex**, plus **Open Plex**, **Shut Down Plex**, **Roll Back**, and **Save Support Report**. No movie, TV episode or music file backup options. Custom Plex folders are available under Advanced.

## Download

[Download version 0.5.0](https://github.com/Amaster15/plex-porter/releases/tag/v0.5.0)

- **Windows:** download `PlexPorter.exe` and run it using the same Windows account as Plex.
- **Xubuntu/Ubuntu:** download `plex-porter_0.5.0_amd64.deb` and install it with the command below.
- **Developers:** source code and build instructions are included in this repository.

This is an early preview. Keep an independent backup and verify your library before removing the original installation. Windows builds are unsigned. Neither this app nor its archives include your movie, episode or music files.

## Quick migration checklist

1. On the old computer, open Plex Porter and click **Export**. If Plex is running, accept the shutdown prompt. Choose a new ZIP filename outside the Plex data folder.
2. Copy the ZIP to the new computer. Keep the old Plex server stopped to avoid duplicate server identities.
3. Install Plex Media Server on the new computer (the **Install Plex** button can help). Run it once to create its data folder, then stop it. You do not need to recreate your libraries.
4. Open Plex Porter on the new computer. Click **Verify a backup**, then **Import**, select the ZIP, and confirm. Wait for **Import complete**.
5. Start Plex yourself: on Linux run `sudo systemctl start plexmediaserver`; on Windows launch Plex Media Server. Click **Open Plex**, sign in with your usual Plex account, and claim the server if prompted.
6. Make your media drives available. Edit each existing Plex library to add its new media folder. Scan and check playback and watched history before removing the old folder paths. Keep automatic trash emptying off until everything is verified.
7. Check sharing and Remote Access. Import removes cached certificates; Plex requests a fresh certificate on startup with internet access. This cannot guarantee remote connectivity.

The app migrates Plex library data and selected settings. Drive mounting, firewall/router setup and Windows file sharing are separate tasks. On Linux, the `plex` service account needs read access to media files and traversal access through their parent folders.

## Downloads and installation

### Windows 10/11, Intel/AMD 64-bit

Run `PlexPorter.exe`. Python, Tk, certificates and application dependencies are embedded; no Python installation is needed. The portable executable does not need to be installed. It is unsigned, so Windows may show an unfamiliar-app warning.

Use the same Windows account that runs Plex. Its settings are stored in that account's registry; running as a different administrator account uses different settings.

### Xubuntu / Ubuntu 22.04 or newer, Intel/AMD 64-bit

Install the supplied Debian package with your package manager, or:

```bash
sudo apt install ./plex-porter_0.5.0_amd64.deb
```

Launch **Plex Porter** from the applications menu. An administrator prompt grants access to Plex's service data. The package includes Python, Tk and application libraries; apt installs the declared standard Linux font/authentication dependencies if missing. It does not need a separate Python setup. The menu launcher is intended for Xubuntu's X11 desktop; other desktops may restrict elevated graphical apps.

## Use

1. Click **Shut Down Plex** and wait for the stopped confirmation. It requests a normal application close on Windows or stops the native `plexmediaserver` systemd service on Linux. Current streams disconnect. It checks that helpers have exited before reporting success; custom service/container installations may need manual shutdown. Disable automatic restarts during migration.
Export, Import and Roll Back also check whether Plex is running. If it is, a popup offers to shut it down and continue automatically. Choosing No cancels the operation; a failed shutdown blocks it. Permission/inspection errors also block the operation instead of assuming Plex is stopped.

2. Click **Export** and choose where to save the ZIP. Standard native Plex data locations are selected automatically. Use Advanced for a custom location.
3. Copy the ZIP to the new computer. **Verify a backup** checks every archived file without changing Plex.
4. If needed, click **Install Plex** on the destination. It downloads the current official package for the local OS, checks Plex's published checksum, and starts installation. Windows additionally checks the installer signature. Internet and administrator approval are required. The button can update an existing Plex installation. Plex itself is not bundled or redistributed.
5. Initialize Plex once, then close/stop it. Click **Import**, select the ZIP, and confirm the destination. Original data is retained as a rollback copy.
6. Start Plex, then click **Open Plex** to open `http://127.0.0.1:32400/web` in your default browser. This button opens the page; it does not start the server. Sign in and claim the restored server.
7. In each existing library, add the new location of its movies/music, scan and verify playback/history, then remove the old location. Keep automatic trash emptying disabled until everything is verified. Do not create replacement libraries.

Your actual media stays on its drives. Mount those drives or copy files separately if needed. This app does not mount drives or change Plex's internal database paths. Automatic scanning and trash emptying are disabled by import. At the end of import the tool checks that no old certificate cache was retained. Plex requests a fresh certificate when it next starts with internet access. This does not guarantee certificate issuance or remote connectivity; verify Remote Access after startup.

## What is included

- Plex's library database: watched history, collections and playlists stored in it.
- Artwork and Plex-generated assets in its internal `Metadata` and `Media` folders. The internal `Media` directory is not your movie/music library; generated thumbnails can still be sizeable.
- Server identity and friendly name, converted between the Windows registry and Linux preferences.

Not included: actual movies/music, source login tokens from native settings, installed plugins/codecs, caches, logs or every platform-specific setting. Claim the restored server and check sharing, transcoding and remote access afterward. Install the same Plex version or a newer one on the destination.

ZIP backups contain private library data and are not encrypted. Keep them private. Hashes detect accidental corruption, not a maliciously rewritten archive. Keep your original server and an independent backup until you have verified the migration. Cross-OS migration is not officially supported by Plex. Plex Porter is independent of Plex, Inc.

## Storage and recovery

Allow up to twice the library-data size during ZIP creation. ZIP64 supports large files; use a filesystem that supports files over 4 GiB. Symlinks, junctions, case-colliding names and Windows-incompatible filenames are rejected rather than silently omitted.

Import verifies into a staging directory before replacing the target. It keeps the old folder beside the target as `Plex Media Server.before-<id>` and writes a `.migration-<id>.json` report. Caught errors roll back. A forced kill or power failure cannot be automatically recovered by a stopped process.

Click **Roll Back**, choose a `Plex Media Server.before-<id>` folder beside the current data folder, and review the confirmation. Plex must be stopped; the tool offers to shut it down. The saved installation replaces the current one, including its saved watched state. The current installation is retained as a new `.before-<id>` copy so the rollback can be undone. Plex remains stopped afterward. Windows restores the matching registry snapshot automatically; use the same Windows account and keep the sibling `.registry.json` file with the rollback folder. This private file can contain account credentials. Rollback does not downgrade the installed Plex executable or touch media files. It requires the saved library database to be present.

## Diagnostic logs

Operations and error tracebacks are saved automatically, including across app restarts. **Save Support Report** exports the recent log history to a text file. Known token/password fields and authorization credentials are redacted before writing. Review filenames and paths before sharing; Plex's own logs, preferences and registry snapshots are not included. Logs rotate at 2 MiB with three older files retained.

Linux logs: `~/.local/state/plex-porter/logs/operations.log` for the account running the tool (normally `/root/.local/state/plex-porter/logs/operations.log` when elevated). Windows logs: `%LOCALAPPDATA%/plex-porter/logs/operations.log`.

After a power interruption, inspect the `.before-<id>` and `.plex-import-*` folders before restarting Plex. A `.plex-porter.lock` blocks concurrent imports; remove a stale lock only after confirming no import is active and recovering the original data if necessary.

## Source and command line

Python 3.10+ and Tkinter are needed only when running from source:

```bash
python -m pip install -e .
python -m plex_porter
python -m unittest discover -s tests -v
```

On Xubuntu install `python3-pip python3-venv python3-tk` first and use a virtual environment. Windows python.org installs normally include Tkinter.

The Linux package also provides the `plex-porter` command:

```bash
sudo plex-porter export /mnt/backup/plex.zip
plex-porter inspect /mnt/backup/plex.zip
sudo plex-porter import /mnt/backup/plex.zip --yes
```

`--data` overrides the Plex folder; import's `--owner` defaults to `plex:plex`. The Windows executable is a desktop build; use the Python source for command-line output on Windows.

## Rebuild

The GitHub Actions workflow tests on Windows and Ubuntu, then produces a Windows executable and a Debian package. It does not publish a release automatically.

Windows:

```powershell
./scripts/build_windows.ps1
```

Ubuntu 22.04:

```bash
sudo apt install python3-pip python3-venv python3-tk libpython3.10 binutils
/usr/bin/python3 -m venv build/venv
source build/venv/bin/activate
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install . pyinstaller
python3 scripts/collect_licenses.py
python3 -m PyInstaller --noconfirm --clean --onedir --add-data "$PWD/build/licenses:licenses" --name PlexPorter --distpath build/linux-dist --workpath build/linux-freeze --specpath build run.py
python3 scripts/build_deb.py build/linux-dist/PlexPorter
```

Build Linux releases on the oldest supported Ubuntu release. See [TESTING.md](TESTING.md) for remaining real-server validation and [FORMAT.md](FORMAT.md) for the library-only archive schema.

[Plex migration guidance](https://support.plex.tv/articles/201370363-move-an-install-to-another-system/) · [Data directories](https://support.plex.tv/articles/202915258-where-is-the-plex-media-server-data-directory-located/)

MIT licensed. Plex is a trademark of Plex, Inc.; no affiliation or endorsement is implied.
