import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from plex_porter import core, rollback, platforms


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'Plex Media Server'
        self.saved = self.root / 'Plex Media Server.before-0123456789ab'
        for folder, label in ((self.target, 'new'), (self.saved, 'old')):
            db = folder / core.DB
            db.parent.mkdir(parents=True)
            db.write_bytes(b'SQLite format 3\0' + label.encode())
            (folder / 'Preferences.xml').write_text(label)
        for name, value in [('ensure_stopped', None), ('host_os', 'linux')]:
            p = patch.object(platforms, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def test_restore_keeps_current_and_can_be_undone(self):
        rollback.restore(self.target, self.saved)
        self.assertEqual((self.target / 'Preferences.xml').read_text(), 'old')
        retained = next(self.root.glob('*.before-*'))
        self.assertEqual((retained / 'Preferences.xml').read_text(), 'new')
        rollback.restore(self.target, retained)
        self.assertEqual((self.target / 'Preferences.xml').read_text(), 'new')

    def test_running_server_and_existing_lock_block_changes(self):
        with patch.object(platforms, 'ensure_stopped', side_effect=platforms.PlexRunningError('running')):
            with self.assertRaises(platforms.PlexRunningError):
                rollback.restore(self.target, self.saved)
        self.target.with_name(self.target.name + '.plex-porter.lock').touch()
        with self.assertRaises(FileExistsError):
            rollback.restore(self.target, self.saved)
        self.assertEqual((self.target / 'Preferences.xml').read_text(), 'new')

    def test_failed_second_rename_restores_original(self):
        original = Path.rename
        def fail(path, dest):
            if path == self.saved:
                raise OSError('simulated disk error')
            return original(path, dest)
        with patch.object(Path, 'rename', fail):
            with self.assertRaisesRegex(OSError, 'simulated'):
                rollback.restore(self.target, self.saved)
        self.assertEqual((self.target / 'Preferences.xml').read_text(), 'new')
        self.assertTrue(self.saved.exists())
        self.assertFalse(self.target.with_name(self.target.name + '.plex-porter.lock').exists())

    def test_plex_restarting_before_swap_preserves_both_folders(self):
        with patch.object(platforms, 'ensure_stopped', side_effect=[None, platforms.PlexRunningError('restarted')]):
            with self.assertRaises(platforms.PlexRunningError):
                rollback.restore(self.target, self.saved)
        self.assertEqual((self.target / 'Preferences.xml').read_text(), 'new')
        self.assertEqual((self.saved / 'Preferences.xml').read_text(), 'old')

    def test_unrelated_folder_and_bad_database_rejected(self):
        with self.assertRaises(ValueError):
            rollback.restore(self.target, self.target)
        (self.saved / core.DB).write_bytes(b'bad')
        with self.assertRaises(ValueError):
            rollback.restore(self.target, self.saved)

    def test_windows_settings_restored_and_saved_for_undo(self):
        keys = {*platforms.PORTABLE, *platforms.SAFE, 'PlexOnlineToken', 'PlexOnlineUsername', 'PlexOnlineMail', 'PlexOnlineHome'}
        before = {k: None for k in keys}
        after = dict(before, FriendlyName=['new', 1])
        rollback.registry_path(self.saved).write_text(json.dumps(before))
        with patch.object(platforms, 'host_os', return_value='windows'), patch.object(platforms, 'registry_snapshot', return_value=after), patch.object(platforms, 'registry_restore') as restore:
            rollback.restore(self.target, self.saved)
        restore.assert_called_once_with(before)
        retained = next(p for p in self.root.glob('*.before-*') if p.is_dir())
        self.assertEqual(json.loads(rollback.registry_path(retained).read_text()), after)

    def test_windows_registry_failure_restores_folders_and_settings(self):
        keys = {*platforms.PORTABLE, *platforms.SAFE, 'PlexOnlineToken', 'PlexOnlineUsername', 'PlexOnlineMail', 'PlexOnlineHome'}
        snapshot = {k: None for k in keys}
        rollback.registry_path(self.saved).write_text(json.dumps(snapshot))
        with patch.object(platforms, 'host_os', return_value='windows'), patch.object(platforms, 'registry_snapshot', return_value=snapshot), patch.object(platforms, 'registry_restore', side_effect=[OSError('registry'), None]) as restore:
            with self.assertRaises(OSError):
                rollback.restore(self.target, self.saved)
        self.assertEqual(restore.call_count, 2)
        self.assertEqual((self.target / 'Preferences.xml').read_text(), 'new')
        self.assertEqual((self.saved / 'Preferences.xml').read_text(), 'old')
