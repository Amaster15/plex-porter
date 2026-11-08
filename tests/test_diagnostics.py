from pathlib import Path
import tempfile
import unittest
from plex_porter.diagnostics import SessionLog, redact


class DiagnosticsTests(unittest.TestCase):
    def test_secret_formats(self):
        for message in ['?X-Plex-Token=SECRET&next=yes', 'X-Plex-Token%3DSECRET%26next%3Dyes',
                        'PlexOnlineToken="SECRET"', '"password": "SECRET"',
                        'Authorization: Bearer SECRET', 'claim-SECRET', 'password="a SECRET phrase"']:
            with self.subTest(message=message):
                self.assertNotIn('SECRET', redact(message))

    def test_log_persists_across_sessions_and_report_redacts(self):
        with tempfile.TemporaryDirectory() as temp:
            log = SessionLog(Path(temp) / 'logs')
            log.write('Failed: X-Plex-Token=SECRET', error=True)
            log.close()
            log = SessionLog(Path(temp) / 'logs')
            try:
                report = Path(temp) / 'report.txt'
                log.save(report)
                self.assertIn('Failed:', report.read_text())
                self.assertNotIn('SECRET', report.read_text())
                self.assertNotIn('SECRET', log.path.read_text())
                with self.assertRaises(ValueError):
                    log.save(log.path)
            finally:
                log.close()
