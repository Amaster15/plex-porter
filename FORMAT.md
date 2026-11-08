# Archive format version 2

A library-only ZIP64 archive contains regular files:

```text
manifest.json
plex/Media/...
plex/Metadata/...
plex/Plug-in Support/Databases/...
```

`plex/Media` contains Plex's generated assets, never user-selected movie or music folders. Version 2 rejects the former preview format and all `media/` payloads. There is no media selection API or CLI option.

The UTF-8 JSON manifest has `format: plex-porter`, `version: 2`, a UTC `created` timestamp, `source_os` (windows/linux), portable `settings`, informational `library_locations`, and `files` mapping each archive filename to `{size, sha256}`. Settings are restricted to the three required server identifiers and optional FriendlyName. The manifest is limited to 64 MiB.

Every payload must appear exactly once and match its declared size and hash. The library DB is required. Unknown payload roots, traversal, absolute paths, Windows reserved names, alternate data streams, case collisions, links, special files, duplicate JSON keys and duplicate ZIP entries are rejected.

Import extracts and verifies into a fresh staging directory, translates settings, disables scans/trash, applies Linux ownership and renames the old data directory to a rollback sibling before placing staged data. Changed Windows registry values are separately snapshotted. Recovery covers caught errors, not power-loss atomicity across a filesystem and registry.

Databases are copied without schema edits. Plex performs any version upgrade on startup; use the same or newer server version. Python SQLite is used only for an optional read of library folder locations. Hashes detect damage, not malicious replacement of both payload and manifest.
