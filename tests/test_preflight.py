import unittest
from unittest.mock import Mock, patch
from plex_porter.gui import App
from plex_porter import platforms


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.app = App.__new__(App)
        self.app.busy = False
        self.app.root = None
        self.app.status = Mock()
        self.app.progress = Mock()
        self.app.run = Mock(side_effect=lambda job: job())
        self.job = Mock(return_value='done')

    def test_stopped_server_continues_without_popup(self):
        with patch('plex_porter.gui.platforms.ensure_stopped') as check, patch('plex_porter.gui.messagebox.askyesno') as popup:
            self.app.run_migration('Export', self.job)
        self.assertEqual(check.call_count, 2)
        popup.assert_not_called()
        self.job.assert_called_once()

    def test_both_actions_offer_shutdown_then_recheck(self):
        for action in ('Export', 'Import', 'Rollback'):
            self.job.reset_mock()
            events = []
            with patch('plex_porter.gui.platforms.ensure_stopped', side_effect=[platforms.PlexRunningError('running'), None]), patch('plex_porter.gui.messagebox.askyesno', return_value=True), patch('plex_porter.gui.controls.shutdown_plex', side_effect=lambda progress: events.append('shutdown')):
                self.job.side_effect = lambda: events.append('operation')
                self.app.run_migration(action, self.job)
            self.assertEqual(events, ['shutdown', 'operation'])

    def test_cancel_changes_nothing(self):
        with patch('plex_porter.gui.platforms.ensure_stopped', side_effect=platforms.PlexRunningError('running')), patch('plex_porter.gui.messagebox.askyesno', return_value=False), patch('plex_porter.gui.controls.shutdown_plex') as stop:
            self.app.run_migration('Import', self.job)
        stop.assert_not_called()
        self.job.assert_not_called()
        self.app.run.assert_not_called()

    def test_shutdown_failure_blocks_operation(self):
        with patch('plex_porter.gui.platforms.ensure_stopped', side_effect=platforms.PlexRunningError('running')), patch('plex_porter.gui.messagebox.askyesno', return_value=True), patch('plex_porter.gui.controls.shutdown_plex', side_effect=RuntimeError('failed')):
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                self.app.run_migration('Import', self.job)
        self.job.assert_not_called()

    def test_restarted_server_blocks_operation(self):
        with patch('plex_porter.gui.platforms.ensure_stopped', side_effect=[None, platforms.PlexRunningError('restarted')]):
            with self.assertRaisesRegex(RuntimeError, 'restarted'):
                self.app.run_migration('Export', self.job)
        self.job.assert_not_called()

    def test_inspection_error_does_not_offer_shutdown_or_write(self):
        with patch('plex_porter.gui.platforms.ensure_stopped', side_effect=RuntimeError('access denied')), patch('plex_porter.gui.messagebox.askyesno') as popup, patch('plex_porter.gui.messagebox.showerror') as error:
            self.app.run_migration('Import', self.job)
        popup.assert_not_called()
        error.assert_called_once()
        self.job.assert_not_called()

    def test_busy_app_does_not_start_second_operation(self):
        self.app.busy = True
        with patch('plex_porter.gui.platforms.ensure_stopped') as check:
            self.app.run_migration('Export', self.job)
        check.assert_not_called()
