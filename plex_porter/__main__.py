import argparse
import json
import traceback
from pathlib import Path
from . import core, platforms, rollback, diagnostics


def main():
    parser = argparse.ArgumentParser(description="Plex Porter — Windows/Linux ZIP migration")
    sub = parser.add_subparsers(dest="command")
    export = sub.add_parser("export", help="Export a stopped Plex library")
    export.add_argument("archive", type=Path)
    export.add_argument("--data", type=Path, default=platforms.default_data())
    inspect = sub.add_parser("inspect", help="Verify a backup without changing Plex")
    inspect.add_argument("archive", type=Path)
    restore = sub.add_parser("import", help="Restore into an initialized, stopped Plex installation")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--data", type=Path, default=platforms.default_data())
    restore.add_argument("--owner", default="plex:plex")
    restore.add_argument("--yes", action="store_true", help="Confirm replacement; original data is kept beside destination")
    undo = sub.add_parser('rollback', help='Restore a local .before- copy; retain current data')
    undo.add_argument('folder', type=Path)
    undo.add_argument('--data', type=Path, default=platforms.default_data())
    undo.add_argument('--yes', action='store_true')
    args = parser.parse_args()
    if args.command is None:
        from .gui import launch
        launch()
        return
    log = diagnostics.SessionLog()
    def progress(message):
        log.write(message)
        print(diagnostics.redact(message))
    try:
        log.write(f'Command: {args.command}')
        if args.command == "export":
            result = core.export_backup(args.data, args.archive, progress)
            print(f"Exported {len(result['files'])} files to {args.archive}")
        elif args.command == "inspect":
            result = core.inspect_backup(args.archive, progress=progress)
            print(json.dumps({k: v for k, v in result.items() if k not in ("files", "settings")}, indent=2))
            print(f"Verified {len(result['files'])} files.")
        elif args.command == 'rollback':
            if not args.yes:
                parser.error('Use --yes to confirm rollback. Current data will be preserved.')
            progress(rollback.restore(args.data, args.folder, progress))
        else:
            if not args.yes:
                parser.error("Review the backup with inspect, then use --yes to confirm import.")
            progress(json.dumps(core.restore_backup(args.archive, args.data, args.owner, progress), indent=2))
        log.write('Command completed')
    except (Exception, KeyboardInterrupt) as error:
        log.write(traceback.format_exc(), error=True)
        parser.exit(1, f"Plex Porter: {diagnostics.redact(error or 'Cancelled')}\nLog: {log.path}\n")
    finally:
        log.close()


if __name__ == "__main__":
    main()
