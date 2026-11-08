import io
import json
import unittest
from unittest.mock import patch
from plex_porter import installer


def metadata():
    def item(build, distro, extension):
        return {"build": build, "distro": distro, "url": "https://downloads.plex.tv/example" + extension, "checksum": "a" * 40}
    return {"computer": {"Windows": {"releases": [item("windows-x86_64", "windows", ".exe")]},
                         "Linux": {"releases": [item("linux-x86_64", "debian", ".deb"), item("linux-aarch64", "debian", ".deb")]}}}


class InstallerTests(unittest.TestCase):
    def test_selects_native_package(self):
        self.assertTrue(installer.choose_release(metadata(), "windows", "AMD64")["url"].endswith(".exe"))
        self.assertEqual(installer.choose_release(metadata(), "linux", "x86_64")["distro"], "debian")
        self.assertEqual(installer.choose_release(metadata(), "linux", "aarch64")["build"], "linux-aarch64")

    def test_rejects_unofficial_or_insecure_urls(self):
        for url in ["http://downloads.plex.tv/app.exe", "https://evil.example/app.exe", "https://plex.tv.evil.example/x", "https://user@plex.tv/x", "https://plex.tv:444/x"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                installer.valid_url(url)

    def test_missing_checksum_rejected(self):
        data = metadata()
        data["computer"]["Windows"]["releases"][0]["checksum"] = ""
        with self.assertRaises(ValueError):
            installer.choose_release(data, "windows", "amd64")

    def test_wrong_architecture_rejected(self):
        with self.assertRaises(ValueError):
            installer.choose_release(metadata(), "windows", "arm64")

    def test_corrupt_download_never_executes(self):
        with patch.object(installer, "host_os", return_value="windows"), \
             patch.object(installer.platform, "machine", return_value="amd64"), \
             patch.object(installer, "open_official", side_effect=[io.BytesIO(json.dumps(metadata()).encode()), io.BytesIO(b"bad installer")]), \
             patch.object(installer.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "checksum"):
                installer.install_plex()
            run.assert_not_called()

    def test_external_tools_do_not_inherit_frozen_library_path(self):
        with patch.dict(installer.os.environ, {"LD_LIBRARY_PATH": "/bundle", "LD_LIBRARY_PATH_ORIG": "/original"}):
            self.assertEqual(installer.external_environment()["LD_LIBRARY_PATH"], "/original")
