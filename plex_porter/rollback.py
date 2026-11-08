"""Restore a local rollback copy while retaining the current installation."""
import json
import os
from pathlib import Path
import re
import uuid
from . import core, platforms


def registry_path(folder):
    return folder.with_name(folder.name + '.registry.json')


def validate(destination, saved):
    destination, saved = Path(destination).expanduser().absolute(), Path(saved).expanduser().absolute()
    for path in (destination, saved):
        if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (path, *path.parents)):
            raise ValueError('Rollback paths cannot contain links or junctions.')
    if saved.parent != destination.parent or not re.fullmatch(re.escape(destination.name) + r'\.before-[0-9a-f]{12}', saved.name):
        raise ValueError('Select a Plex Porter .before- rollback folder beside the current data folder.')
    if not destination.is_dir():
        raise ValueError('The current Plex data folder is missing.')
    core.check_database(saved / core.DB)
    snapshot = None
    if platforms.host_os() == 'windows':
        path = registry_path(saved)
        if path.is_symlink() or path.stat().st_size > 1024 * 1024:
            raise ValueError('Invalid registry rollback file.')
        snapshot = json.loads(path.read_text(encoding='utf-8'))
        allowed = {*platforms.PORTABLE, *platforms.SAFE, 'PlexOnlineToken', 'PlexOnlineUsername', 'PlexOnlineMail', 'PlexOnlineHome'}
        if not isinstance(snapshot, dict) or set(snapshot) != allowed:
            raise ValueError('Registry rollback keys are incomplete or unsupported.')
        for entry in snapshot.values():
            if entry is not None and (not isinstance(entry, list) or len(entry) != 2 or
                    not ((entry[1] == 1 and isinstance(entry[0], str)) or
                         (entry[1] == 4 and type(entry[0]) is int))):
                raise ValueError('Unsupported registry rollback value.')
    return destination, saved, snapshot


def restore(destination, saved, progress=lambda message: None):
    platforms.ensure_stopped()
    destination, saved, snapshot = validate(destination, saved)
    lock = destination.with_name(destination.name + '.plex-porter.lock')
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    current = destination.with_name(destination.name + '.before-' + uuid.uuid4().hex[:12])
    previous_registry = None
    moved_current = moved_saved = committed = False
    try:
        if snapshot is not None:
            previous_registry = platforms.registry_snapshot()
            with os.fdopen(os.open(registry_path(current), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w', encoding='utf-8') as out:
                json.dump(previous_registry, out)
        progress(f'Restoring previous installation: {saved}')
        platforms.ensure_stopped()
        destination.rename(current)
        moved_current = True
        saved.rename(destination)
        moved_saved = True
        if snapshot is not None:
            platforms.registry_restore(snapshot)
        committed = True
    except BaseException:
        if moved_saved:
            destination.rename(saved)
        if moved_current:
            current.rename(destination)
        if previous_registry is not None:
            platforms.registry_restore(previous_registry)
        raise
    finally:
        lock.unlink(missing_ok=True)
        if not committed and not moved_current:
            registry_path(current).unlink(missing_ok=True)
    return f'Previous installation restored. Plex is stopped.\nStart Plex when ready.\nThe installation you replaced is preserved at:\n{current}\nMedia files were not changed.'
