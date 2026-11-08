# Release validation

Automated tests run entirely on synthetic fixtures. Native Windows behavior, GUI appearance and actual Plex compatibility require this manual gate before calling a release production-ready.

## Matrix

- Windows 11 native Plex -> Xubuntu native .deb Plex
- Xubuntu native .deb Plex -> Windows 11 native Plex
- Same-OS recovery on each platform
- Python source launch and packaged executable launch

## Procedure

1. Use disposable VMs with the same Plex version. Add a small movie and music library, a custom poster, watched/unwatched items, a collection and playlist.
2. Export with Plex running: expect rejection. Stop it and export library data only.
3. Verify ZIP hashes. Transfer the ZIP and initialize/stop the destination Plex installation.
4. Preview destination paths and import. Confirm originals and any changed Windows registry values have rollback copies.
5. Start/claim Plex; verify server identity, collections, posters, playlists, watched state and user access. Add new media roots to existing libraries, scan and verify playback.
6. Verify no automatic trash emptying or background scanning was enabled by import. Confirm native destination preferences are appropriate; test hardware transcoding and remote access separately.
7. Reboot. Verify mounts, ownership and playback without an interactive login on Linux.
8. Stop Plex, perform documented rollback, and verify the original server works.
9. Test large ZIP64 archives and a non-ASCII media filename. Check a full disk, read-only target, permissions failure and destination mountpoint fail safely.
10. Check GUI at 100% and 150% scaling; browse fields, export progress, validation errors, import confirmation, and final report.

Containers, NAS packages, custom Windows service accounts, mounted data directories and other Linux distributions are not validated by this initial native-installation scope. Symlink/junction-based source layouts are rejected. Resolve these explicitly before broadening support.

## Current local validation

Local package builds use an isolated Ubuntu 22.04 filesystem and Windows Python under Wine. Virtual-display smoke tests check the GUI. Fixture tests do not certify actual Plex migrations; native Windows and real-server validation remain release gates. The Install Plex button is tested with fixture metadata and corrupt downloads; the real installer is not executed on the development machine. GitHub CI has not run until the repository is published.

Version 0.5.0: 63 automated tests passed on host Linux, isolated Ubuntu 22.04, and Windows Python under Wine. Includes rollback reversal/failure recovery, Windows registry restoration, process guards for all three migration actions, persistent log redaction, and certificate cache exclusion. Packaged Linux rollback tested against disposable data; Linux and Windows packaged GUIs launched and visually checked. Actual certificate issuance and real-server rollback remain manual integration checks.
