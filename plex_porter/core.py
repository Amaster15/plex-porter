"""Streaming ZIP64 backups, strict validation, and staged transactional restore."""
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from . import platforms as native

FORMAT = "plex-porter"
VERSION = 2
DB = "Plug-in Support/Databases/com.plexapp.plugins.library.db"
ROOTS = ("Media", "Metadata", "Plug-in Support/Databases")
CHUNK = 1024 * 1024
MAX_MANIFEST = 64 * 1024 * 1024
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


def safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name or name.startswith("/"):
        raise ValueError(f"Unsafe archive path: {name!r}")
    parts = name.split("/")
    for part in parts:
        if part in ("", ".", "..") or part.endswith((" ", ".")) or RESERVED.match(part):
            raise ValueError(f"Nonportable archive path: {name!r}")
        if any(ord(c) < 32 or c in '<>:"|?*' for c in part):
            raise ValueError(f"Nonportable archive path: {name!r}")
    return PurePosixPath(name)


def inside(path, parent):
    return path == parent or parent in path.parents


def regular_files(root):
    root = Path(root)
    if root.is_symlink():
        raise ValueError(f"Symbolic links are not supported: {root}")
    def failed(error):
        raise error
    for base, dirs, files in os.walk(root, onerror=failed):
        for name in dirs + files:
            item = Path(base) / name
            if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
                raise ValueError(f"Links/junctions are not supported: {item}")
        for name in sorted(files):
            item = Path(base) / name
            if not stat.S_ISREG(item.stat().st_mode):
                raise ValueError(f"Not a regular file: {item}")
            yield item


def library_locations(data):
    try:
        uri = (Path(data) / DB).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            return [row[0] for row in connection.execute("SELECT root_path FROM section_locations")]
    except sqlite3.Error:
        return []


def check_database(path):
    if not Path(path).is_file():
        raise ValueError("Plex library database is missing.")
    with open(path, "rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            raise ValueError("Library database does not have a SQLite header.")


def export_backup(data, output, progress=lambda message: None):
    native.ensure_stopped()
    data, output = Path(data).resolve(), Path(output).resolve()
    check_database(data / DB)
    settings = native.read_settings(data)
    native.validate_settings(settings)
    if output.exists():
        raise FileExistsError("Choose a new ZIP filename; backups are never overwritten.")
    output.parent.mkdir(parents=True, exist_ok=True)
    if inside(output, data):
        raise ValueError("Save the ZIP outside the Plex data folder.")
    entries, names = [], set()
    for root in ROOTS:
        if (data / root).exists():
            entries.extend((p, "plex/" + p.relative_to(data).as_posix()) for p in regular_files(data / root))
    check_path_collisions(name for _, name in entries)
    total = sum(p.stat().st_size for p, _ in entries)
    if shutil.disk_usage(output.parent).free < 2 * total + 64 * 1024 * 1024:
        raise OSError("Not enough space: allow twice the source size while the ZIP is finalized.")
    manifest = {"format": FORMAT, "version": VERSION, "created": datetime.now(timezone.utc).isoformat(),
                "source_os": native.host_os(), "settings": settings,
                "library_locations": library_locations(data), "files": {}}
    fd, temp_name = tempfile.mkstemp(prefix=".plex-export-", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as archive:
            for index, (path, name) in enumerate(entries):
                safe_name(name)
                if name.casefold() in names:
                    raise ValueError(f"Case-insensitive filename collision: {name}")
                names.add(name.casefold())
                before = path.stat()
                digest, count = hashlib.sha256(), 0
                progress(f"Packing {index + 1}/{len(entries)}: {name}")
                with path.open("rb") as source, archive.open(name, "w", force_zip64=True) as target:
                    while chunk := source.read(CHUNK):
                        target.write(chunk)
                        digest.update(chunk)
                        count += len(chunk)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or count != before.st_size:
                    raise RuntimeError(f"Source changed during backup: {path}")
                manifest["files"][name] = {"size": count, "sha256": digest.hexdigest()}
            native.ensure_stopped()
            encoded = json.dumps(manifest, indent=2).encode()
            if len(encoded) > MAX_MANIFEST:
                raise ValueError("Too many files for this archive format version.")
            archive.writestr("manifest.json", encoded)
        # Exclusive publication: even another process creating the output cannot be overwritten.
        with temp.open("rb") as source, os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as target:
            try:
                shutil.copyfileobj(source, target, CHUNK)
            except BaseException:
                target.close()
                output.unlink(missing_ok=True)
                raise
        progress(f"Export complete: {output}")
        return manifest
    finally:
        temp.unlink(missing_ok=True)


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key in manifest.")
        result[key] = value
    return result


def check_path_collisions(names):
    seen = {}
    for name in names:
        for path in (PurePosixPath(name), *PurePosixPath(name).parents):
            spelling = str(path)
            key = spelling.casefold()
            if key in seen and seen[key] != spelling:
                raise ValueError(f"Case-insensitive path collision: {spelling}")
            seen[key] = spelling


def _manifest(archive):
    infos = archive.infolist()
    names, folded = {}, set()
    for info in infos:
        safe_name(info.filename)
        if info.is_dir() or info.filename.casefold() in folded:
            raise ValueError("Duplicate filenames or directory entries in archive.")
        mode = info.external_attr >> 16
        if stat.S_IFMT(mode) not in (0, stat.S_IFREG) or info.flag_bits & 1:
            raise ValueError("Links, special files and encrypted ZIP entries are unsupported.")
        folded.add(info.filename.casefold())
        names[info.filename] = info
    check_path_collisions(names)
    if "manifest.json" not in names or names["manifest.json"].file_size > MAX_MANIFEST:
        raise ValueError("Missing or oversized Plex Porter manifest.")
    manifest = json.loads(archive.read("manifest.json"), object_pairs_hook=_unique_json)
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
        raise ValueError("Not a supported Plex Porter backup.")
    native.validate_settings(manifest.get("settings"))
    if manifest.get("source_os") not in ("windows", "linux"):
        raise ValueError("Invalid source operating system.")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(names) - {"manifest.json"}:
        raise ValueError("Manifest and ZIP contents do not match.")
    if "plex/" + DB not in files:
        raise ValueError("Archive is missing the Plex library database.")
    if manifest.get("media"):
        raise ValueError("Media-file archives are unsupported; export a library-only backup.")
    for name, meta in files.items():
        allowed = any(name.startswith("plex/" + root + "/") for root in ROOTS)
        if not allowed or not isinstance(meta, dict):
            raise ValueError(f"Unsupported archive entry: {name}")
        if type(meta.get("size")) is not int or meta["size"] < 0 or meta["size"] != names[name].file_size:
            raise ValueError(f"Invalid file size: {name}")
        if not isinstance(meta.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", meta["sha256"]):
            raise ValueError(f"Invalid checksum: {name}")
        for parent in PurePosixPath(name).parents:
            if str(parent).casefold() in folded:
                raise ValueError("Archive has a file/directory path collision.")
    return manifest


def inspect_backup(archive_path, verify=True, progress=lambda message: None):
    with zipfile.ZipFile(archive_path) as archive:
        manifest = _manifest(archive)
        if verify:
            for index, (name, meta) in enumerate(manifest["files"].items()):
                progress(f"Verifying {index + 1}/{len(manifest['files'])}: {name}")
                digest = hashlib.sha256()
                with archive.open(name) as stream:
                    while chunk := stream.read(CHUNK):
                        digest.update(chunk)
                if digest.hexdigest() != meta["sha256"]:
                    raise ValueError(f"Checksum mismatch: {name}")
        return manifest


def restore_backup(archive_path, destination, owner="plex:plex", progress=lambda message: None):
    destination = Path(destination).expanduser().absolute()
    lock = destination.with_name(destination.name + ".plex-porter.lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(f"Another import may be active. Lock: {lock}") from exc
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        return _restore_backup(archive_path, destination, owner, progress)
    finally:
        lock.unlink(missing_ok=True)


def _restore_backup(archive_path, destination, owner="plex:plex", progress=lambda message: None):
    """Restore into an initialized, stopped native Plex installation. Keep rollback sibling."""
    native.ensure_stopped()
    raw_destination = Path(destination).expanduser().absolute()
    if raw_destination.is_symlink() or any(p.is_symlink() for p in raw_destination.parents):
        raise ValueError("Destination cannot use symlinks.")
    destination = raw_destination.resolve()
    if not destination.is_dir() or not (destination / "Plug-in Support").is_dir():
        raise ValueError("Select an initialized Plex data folder. Install and run Plex once, then stop it.")
    ids = native.owner_ids(owner)
    # Verify ownership changes are permitted before doing expensive work.
    if ids is not None and os.geteuid() != 0 and ids != (os.geteuid(), os.getegid()):
        raise PermissionError("Linux import needs sudo to assign Plex ownership (or use your own service owner).")
    archive_path = Path(archive_path).resolve()
    if inside(archive_path, destination):
        raise ValueError("Backup ZIP must be outside the destination Plex directory.")
    stamp = uuid.uuid4().hex[:12]
    rollback = destination.with_name(destination.name + ".before-" + stamp)
    stage = Path(tempfile.mkdtemp(prefix=".plex-import-", dir=destination.parent))
    swapped = False
    registry = None
    registry_file = None
    try:
        with zipfile.ZipFile(archive_path) as archive:
            manifest = _manifest(archive)
            required = sum(m["size"] for m in manifest["files"].values())
            if shutil.disk_usage(stage).free < required + 64 * CHUNK:
                raise OSError("Not enough space to stage the restore.")
            for index, (name, meta) in enumerate(manifest["files"].items()):
                relative = PurePosixPath(name)
                target = stage.joinpath(*relative.parts[1:])
                target.parent.mkdir(parents=True, exist_ok=True)
                progress(f"Restoring {index + 1}/{len(manifest['files'])}: {name}")
                digest = hashlib.sha256()
                with archive.open(name) as source, target.open("xb") as output:
                    while chunk := source.read(CHUNK):
                        output.write(chunk)
                        digest.update(chunk)
                if digest.hexdigest() != meta["sha256"]:
                    raise ValueError(f"Checksum mismatch: {name}")
        check_database(stage / DB)
        # Keep target-specific settings, translate only portable values, and disable scans/trash.
        if native.host_os() == "linux":
            native.write_linux_settings(stage, destination, manifest["settings"])
        else:
            registry = native.registry_snapshot()
            registry_file = rollback.with_suffix(rollback.suffix + ".registry.json")
            with registry_file.open("x", encoding="utf-8") as stream:
                json.dump(registry, stream, indent=2)
        native.apply_owner(stage, ids)
        native.ensure_stopped()
        destination.rename(rollback)
        swapped = True
        stage.rename(destination)
        if registry is not None:
            native.write_windows_settings(manifest["settings"])
        # Cache is deliberately excluded from the archive and the replacement
        # directory. Never copy the old installation's TLS credentials back.
        # Certificate issuance requires Plex itself to start and reach plex.tv.
        if (destination / 'Cache').exists():
            raise RuntimeError('Import unexpectedly retained a cache; certificate refresh cannot be assured.')
        progress('Certificate cache cleared. Plex will request a fresh certificate on its next start.')
        report = {"rollback": str(rollback), "registry_backup": str(registry_file) if registry_file else None,
                  "certificate_refresh": "Pending Plex startup and internet access; no cached certificate was retained. Remote access still needs verification.",
                  "old_library_locations": manifest.get("library_locations", []),
                  "next_steps": "Start Plex, claim it locally, add new folders to existing libraries, scan and verify before removing old paths. Keep automatic trash disabled until verified."}
        report_path = destination.with_name(destination.name + ".migration-" + stamp + ".json")
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        progress(f"Import complete. Report: {report_path}")
        return report
    except BaseException:
        if swapped:
            if destination.exists():
                destination.rename(stage)
            rollback.rename(destination)
            if registry is not None:
                native.registry_restore(registry)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
