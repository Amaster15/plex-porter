from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from plex_porter import core, platforms

SETTINGS = {"MachineIdentifier": "original-machine", "ProcessedMachineIdentifier": "processed-machine",
            "AnonymousMachineIdentifier": "anonymous-machine", "FriendlyName": "Movies & Music"}


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.target = self.base / "destination"
        self.archive = self.base / "backup.zip"
        self.make_plex(self.source)
        self.make_plex(self.target)
        (self.target / "old-only.txt").write_text("keep for rollback")
        for target, value in [("ensure_stopped", None), ("owner_ids", None), ("host_os", "linux")]:
            p = patch.object(platforms, target, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def make_plex(self, folder):
        db = folder / core.DB
        db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(db)) as c:
            c.execute("CREATE TABLE section_locations (root_path TEXT)")
            c.execute("INSERT INTO section_locations VALUES (?)", (r"D:\Movies",))
            c.execute("CREATE TABLE watched (title TEXT, watched INTEGER)")
            c.execute("INSERT INTO watched VALUES ('A film', 1)")
            c.commit()
        (folder / "Metadata").mkdir()
        (folder / "Metadata" / "poster.jpg").write_bytes(b"poster" * 400)
        (folder / "Media").mkdir()
        (folder / "Media" / "thumb.jpg").write_bytes(b"thumb")
        root = ET.Element("Preferences", {**SETTINGS, "PlexOnlineToken": "SECRET", "TranscoderTempDirectory": "/tmp/transcode"})
        ET.ElementTree(root).write(folder / "Preferences.xml")
        (folder / "Cache").mkdir()
        (folder / "Cache" / "ignore").write_text("cache")

    def export(self, **kwargs):
        return core.export_backup(self.source, self.archive, **kwargs)

    def rewrite(self, mutate):
        with zipfile.ZipFile(self.archive) as z:
            files = {name: z.read(name) for name in z.namelist()}
        mutate(files)
        with zipfile.ZipFile(self.archive, "w") as z:
            for name, value in files.items():
                z.writestr(name, value)

    def test_roundtrip_keeps_database_artwork_and_rollback(self):
        (self.target / 'Cache' / 'certificate.p12').write_bytes(b'old certificate')
        (self.target / 'Cache' / 'cert-v2.p12').write_bytes(b'old alternate certificate')
        self.export()
        core.inspect_backup(self.archive)
        report = core.restore_backup(self.archive, self.target)
        self.assertEqual((self.source / core.DB).read_bytes(), (self.target / core.DB).read_bytes())
        self.assertEqual((self.target / "Metadata/poster.jpg").read_bytes(), b"poster" * 400)
        self.assertTrue((Path(report["rollback"]) / "old-only.txt").exists())
        self.assertFalse((self.target / 'Cache').exists())
        self.assertEqual((Path(report['rollback']) / 'Cache/certificate.p12').read_bytes(), b'old certificate')
        self.assertIn('Pending Plex startup', report['certificate_refresh'])
        settings = ET.parse(self.target / "Preferences.xml").getroot().attrib
        self.assertEqual(settings["MachineIdentifier"], SETTINGS["MachineIdentifier"])
        self.assertEqual(settings["autoEmptyTrash"], "0")
        self.assertEqual(settings["TranscoderTempDirectory"], "/tmp/transcode")
        self.assertNotIn("PlexOnlineToken", settings)
        with closing(sqlite3.connect(self.target / core.DB)) as c:
            self.assertEqual(c.execute("SELECT watched FROM watched").fetchone()[0], 1)

    def test_zip_excludes_tokens_cache_and_native_settings(self):
        self.export()
        with zipfile.ZipFile(self.archive) as z:
            self.assertFalse(any("Cache" in name or "Preferences.xml" in name for name in z.namelist()))
            self.assertNotIn(b"SECRET", z.read("manifest.json"))

    def test_media_payload_rejected(self):
        self.export()
        def mutate(files):
            files["media/000/movie.mkv"] = b"video"
            m = json.loads(files["manifest.json"])
            import hashlib
            m["files"]["media/000/movie.mkv"] = {"size": 5, "sha256": hashlib.sha256(b"video").hexdigest()}
            files["manifest.json"] = json.dumps(m).encode()
        self.rewrite(mutate)
        with self.assertRaisesRegex(ValueError, "Unsupported archive entry"):
            core.restore_backup(self.archive, self.target)
        self.assertTrue((self.target / "old-only.txt").exists())

    def test_corruption_leaves_destination_untouched(self):
        self.export()
        self.rewrite(lambda files: files.__setitem__("plex/Metadata/poster.jpg", b"broken" * 400))
        with self.assertRaises(ValueError):
            core.restore_backup(self.archive, self.target)
        self.assertTrue((self.target / "old-only.txt").exists())
        self.assertFalse(list(self.base.glob(".plex-import-*")))

    def test_equal_size_corruption_detected_by_hash(self):
        self.export()
        self.rewrite(lambda files: files.__setitem__("plex/Media/thumb.jpg", b"wrong"))
        with self.assertRaisesRegex(ValueError, "Checksum"):
            core.inspect_backup(self.archive)

    def test_zip_slip_blocked(self):
        self.export()
        self.rewrite(lambda files: files.__setitem__("../escaped", b"bad"))
        with self.assertRaises(ValueError):
            core.restore_backup(self.archive, self.target)
        self.assertFalse((self.base / "escaped").exists())

    def test_windows_unsafe_names(self):
        for name in ["C:/windows", "plex/CON.txt", "plex/a.", "plex/a ", "plex/a:b", "plex/../a", "plex\\a", "/root"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                core.safe_name(name)

    def test_unlisted_entry_rejected(self):
        self.export()
        self.rewrite(lambda files: files.__setitem__("plex/Media/extra", b"x"))
        with self.assertRaisesRegex(ValueError, "contents"):
            core.inspect_backup(self.archive)

    def test_duplicate_zip_entries_rejected(self):
        self.export()
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with zipfile.ZipFile(self.archive, "a") as z:
                z.writestr("manifest.json", "{}")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            core.inspect_backup(self.archive)

    def test_export_refuses_running_plex(self):
        with patch.object(platforms, "ensure_stopped", side_effect=RuntimeError("Plex is running")):
            with self.assertRaises(RuntimeError):
                self.export()
        self.assertFalse(self.archive.exists())

    def test_existing_backup_untouched(self):
        self.archive.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            self.export()
        self.assertEqual(self.archive.read_bytes(), b"existing")

    def test_output_inside_source_rejected(self):
        with self.assertRaises(ValueError):
            core.export_backup(self.source, self.source / "backup.zip")

    def test_identity_required(self):
        ET.ElementTree(ET.Element("Preferences")).write(self.source / "Preferences.xml")
        with self.assertRaisesRegex(ValueError, "identity"):
            self.export()

    def test_missing_database_rejected(self):
        (self.source / core.DB).unlink()
        with self.assertRaises(ValueError):
            self.export()

    def test_low_disk_space_refused(self):
        from collections import namedtuple
        usage = namedtuple("usage", "total used free")(100, 99, 1)
        with patch("plex_porter.core.shutil.disk_usage", return_value=usage):
            with self.assertRaises(OSError):
                self.export()

    def test_symlink_export_rejected(self):
        link = self.source / "Metadata/link"
        try:
            link.symlink_to(self.source / "Media/thumb.jpg")
        except OSError:
            self.skipTest("Symlink creation unavailable")
        with self.assertRaisesRegex(ValueError, "Links"):
            self.export()

    def test_windows_export_linux_import(self):
        with patch.object(platforms, "host_os", return_value="windows"), patch.object(platforms, "read_settings", return_value=SETTINGS):
            self.export()
        self.assertEqual(core.inspect_backup(self.archive)["source_os"], "windows")
        core.restore_backup(self.archive, self.target)
        self.assertEqual(ET.parse(self.target / "Preferences.xml").getroot().get("MachineIdentifier"), "original-machine")

    def test_linux_export_windows_import(self):
        self.export()
        snapshot = {"MachineIdentifier": ["old", 1]}
        with patch.object(platforms, "host_os", return_value="windows"), \
             patch.object(platforms, "registry_snapshot", return_value=snapshot), \
             patch.object(platforms, "write_windows_settings") as write:
            report = core.restore_backup(self.archive, self.target)
        write.assert_called_once_with(SETTINGS)
        self.assertEqual(json.loads(Path(report["registry_backup"]).read_text()), snapshot)
        self.assertTrue((self.target / core.DB).exists())

    def test_failed_windows_settings_rolls_back_data_and_registry(self):
        self.export()
        snapshot = {"MachineIdentifier": ["old", 1]}
        with patch.object(platforms, "host_os", return_value="windows"), \
             patch.object(platforms, "registry_snapshot", return_value=snapshot), \
             patch.object(platforms, "write_windows_settings", side_effect=OSError("registry failed")), \
             patch.object(platforms, "registry_restore") as undo:
            with self.assertRaisesRegex(OSError, "registry failed"):
                core.restore_backup(self.archive, self.target)
        undo.assert_called_once_with(snapshot)
        self.assertTrue((self.target / "old-only.txt").exists())

    def test_failure_after_swap_rolls_back_database(self):
        self.export()
        real_write = Path.write_text
        def fail_report(path, *args, **kwargs):
            if ".migration-" in path.name:
                raise OSError("report failed")
            return real_write(path, *args, **kwargs)
        with patch.object(Path, "write_text", fail_report):
            with self.assertRaisesRegex(OSError, "report failed"):
                core.restore_backup(self.archive, self.target)
        self.assertTrue((self.target / "old-only.txt").exists())

    def test_case_colliding_directories_rejected(self):
        with self.assertRaisesRegex(ValueError, "collision"):
            core.check_path_collisions(["plex/Media/Folder/a", "plex/Media/folder/b"])

    def test_concurrent_import_lock_rejected(self):
        self.export()
        lock = self.target.with_name(self.target.name + ".plex-porter.lock")
        lock.write_text("123")
        with self.assertRaisesRegex(RuntimeError, "Another import"):
            core.restore_backup(self.archive, self.target)
        self.assertTrue(lock.exists())
        self.assertTrue((self.target / "old-only.txt").exists())

    def test_failed_ownership_keeps_original(self):
        self.export()
        with patch.object(platforms, "apply_owner", side_effect=PermissionError("no ownership")):
            with self.assertRaises(PermissionError):
                core.restore_backup(self.archive, self.target)
        self.assertTrue((self.target / "old-only.txt").exists())
        self.assertFalse(list(self.base.glob("*.plex-porter.lock")))

    def test_cancelled_export_cleans_partial(self):
        def cancel(_):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.export(progress=cancel)
        self.assertFalse(self.archive.exists())
        self.assertFalse(list(self.base.glob(".plex-export-*")))

    def test_unknown_settings_rejected(self):
        self.export()
        def mutate(files):
            m = json.loads(files["manifest.json"])
            m["settings"]["PlexOnlineToken"] = "not allowed"
            files["manifest.json"] = json.dumps(m).encode()
        self.rewrite(mutate)
        with self.assertRaisesRegex(ValueError, "unsupported settings"):
            core.inspect_backup(self.archive)

    def test_zip_symlink_rejected(self):
        self.export()
        info = zipfile.ZipInfo("plex/Metadata/link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        with zipfile.ZipFile(self.archive, "a") as z:
            z.writestr(info, "../../outside")
        with self.assertRaisesRegex(ValueError, "Links"):
            core.inspect_backup(self.archive)

    def test_import_refuses_running_plex(self):
        self.export()
        with patch.object(platforms, 'ensure_stopped', side_effect=platforms.PlexRunningError('running')):
            with self.assertRaises(platforms.PlexRunningError):
                core.restore_backup(self.archive, self.target)
        self.assertTrue((self.target / 'old-only.txt').exists())


if __name__ == "__main__":
    unittest.main()
