from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
from plex_porter import controls


class ControlTests(unittest.TestCase):
    def test_windows_opens_local_default_browser(self):
        with patch.object(controls.platforms, 'host_os', return_value='windows'), patch.object(controls.os, 'startfile', create=True) as start:
            controls.open_plex()
            start.assert_called_once_with('http://127.0.0.1:32400/web')

    def test_linux_root_opens_as_desktop_user(self):
        user = SimpleNamespace(pw_name='alice', pw_dir='/home/alice')
        import sys
        with patch.object(controls.platforms, 'host_os', return_value='linux'), patch.object(controls.os, 'geteuid', return_value=0, create=True), patch.dict(controls.os.environ, {'PKEXEC_UID':'1000'}), patch.dict(sys.modules, {'pwd':SimpleNamespace(getpwuid=lambda uid: user)}), patch.object(controls.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            controls.open_plex()
            args=run.call_args.args[0]
            self.assertEqual(args[:4], ['/usr/sbin/runuser','-u','alice','--'])
            self.assertIn('HOME=/home/alice',args)
            self.assertEqual(args[-1],controls.PLEX_URL)

    def test_root_without_desktop_user_does_not_launch_browser(self):
        with patch.object(controls.platforms,'host_os',return_value='linux'), patch.object(controls.os,'geteuid',return_value=0,create=True), patch.dict(controls.os.environ,{'PKEXEC_UID':'','SUDO_UID':''}), patch.dict(sys.modules, {'pwd':SimpleNamespace()}), patch.object(controls.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'No original desktop user'):
                controls.open_plex()
            run.assert_not_called()

    def test_already_stopped_does_not_issue_command(self):
        with patch.object(controls.platforms,'ensure_stopped'), patch.object(controls.subprocess,'run') as run:
            self.assertIn('already stopped',controls.shutdown_plex())
            run.assert_not_called()

    def test_linux_stops_native_service_and_waits(self):
        with patch.object(controls.platforms,'host_os',return_value='linux'), patch.object(controls.os,'geteuid',return_value=0,create=True), patch.object(controls.platforms,'ensure_stopped',side_effect=[RuntimeError('running'),RuntimeError('running'),None]), patch.object(controls.time,'sleep'), patch.object(controls.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            self.assertIn('Plex is stopped',controls.shutdown_plex())
            self.assertEqual(run.call_args.args[0],['/usr/bin/systemctl','stop','--no-block','plexmediaserver.service'])

    def test_windows_never_force_kills(self):
        process=SimpleNamespace(name=lambda:'Plex Media Server.exe',pid=123)
        with patch.object(controls.platforms,'host_os',return_value='windows'), patch.object(controls.platforms,'ensure_stopped',side_effect=[RuntimeError('running'),None]), patch.object(controls.psutil,'process_iter',return_value=[process]), patch.object(controls.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            self.assertIn('Plex is stopped',controls.shutdown_plex())
            self.assertEqual(run.call_args.args[0],['taskkill.exe','/PID','123'])

    def test_timeout_does_not_claim_success(self):
        with patch.object(controls.platforms,'host_os',return_value='linux'), patch.object(controls.os,'geteuid',return_value=0,create=True), patch.object(controls.platforms,'ensure_stopped',side_effect=RuntimeError('running')), patch.object(controls.subprocess,'run',return_value=SimpleNamespace(returncode=0)):
            with self.assertRaisesRegex(RuntimeError,'not fully stopped'):
                controls.shutdown_plex(timeout=0)

    def test_service_failure_reported(self):
        with patch.object(controls.platforms,'host_os',return_value='linux'), patch.object(controls.os,'geteuid',return_value=0,create=True), patch.object(controls.platforms,'ensure_stopped',side_effect=RuntimeError('running')), patch.object(controls.subprocess,'run',return_value=SimpleNamespace(returncode=1,stderr='Access denied',stdout='')):
            with self.assertRaisesRegex(RuntimeError,'Access denied'):
                controls.shutdown_plex()
