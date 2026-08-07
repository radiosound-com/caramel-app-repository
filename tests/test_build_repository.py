import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from build_repository import RepositoryError, build_index, inspect_apk, sha256_file


class RepositoryBuilderTest(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            "repository": {
                "name": "Test",
                "description": "Test repository",
                "url": "https://example.test/fdroid/repo",
            },
            "packages": {
                "com.example.app": {
                    "display_name": "Example",
                    "summary": "Summary",
                    "description": "Description",
                    "categories": ["System"],
                    "license": "Apache-2.0",
                    "source_code": "https://example.test/source",
                    "trusted_signing_certificate_sha256": "a" * 64,
                    "manifest_findings": {"automotive_candidate": True},
                }
            },
        }

    def test_builds_pinned_first_party_entry(self):
        release = {
            "package_name": "com.example.app",
            "version_code": 7,
            "version_name": "1.2.3",
            "downloaded_size": 42,
            "sha256": "b" * 64,
            "signing_certificate_sha256": "a" * 64,
        }
        index = build_index(self.manifest, [release])
        entry = index["packages"][0]
        self.assertEqual(7, entry["version_code"])
        self.assertEqual("https://example.test/fdroid/repo/com.example.app_7.apk", entry["apk_url"])
        self.assertTrue(entry["first_party"])
        self.assertEqual("a" * 64, entry["signing_certificate_sha256"])

    def test_includes_localized_icon_and_screenshots(self):
        release = {
            "package_name": "com.example.app",
            "version_code": 7,
            "version_name": "1.2.3",
            "downloaded_size": 42,
            "sha256": "b" * 64,
            "signing_certificate_sha256": "a" * 64,
        }
        fdroid_index = {
            "packages": {
                "com.example.app": {
                    "metadata": {
                        "icon": {"en-US": {"name": "/icons/example.png"}},
                        "screenshots": {
                            "phone": {
                                "en-US": [
                                    {"name": "/com.example.app/en-US/phoneScreenshots/1.png"},
                                    {"name": "/com.example.app/en-US/phoneScreenshots/2.png"},
                                ]
                            }
                        },
                    }
                }
            }
        }
        entry = build_index(self.manifest, [release], fdroid_index)["packages"][0]
        self.assertEqual(
            "https://example.test/fdroid/repo/icons/example.png",
            entry["metadata"]["icon_url"],
        )
        self.assertEqual(
            [
                "https://example.test/fdroid/repo/com.example.app/en-US/phoneScreenshots/1.png",
                "https://example.test/fdroid/repo/com.example.app/en-US/phoneScreenshots/2.png",
            ],
            entry["metadata"]["screenshot_urls"],
        )

    def test_rejects_unexpected_signer(self):
        release = {
            "package_name": "com.example.app",
            "version_code": 7,
            "version_name": "1.2.3",
            "downloaded_size": 42,
            "sha256": "b" * 64,
            "signing_certificate_sha256": "c" * 64,
        }
        with self.assertRaisesRegex(RepositoryError, "signer"):
            build_index(self.manifest, [release])

    def test_inspects_package_version_and_signer(self):
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "example.apk"
            apk.write_bytes(b"apk")
            outputs = [
                "package: name='com.example.app' versionCode='7' versionName='1.2.3'\n",
                "Signer #1 certificate SHA-256 digest: " + "a" * 64 + "\n",
            ]
            with patch("build_repository.run", side_effect=outputs):
                result = inspect_apk(apk, "aapt2", "apksigner")
            self.assertEqual("com.example.app", result["package_name"])
            self.assertEqual(7, result["version_code"])
            self.assertEqual(hashlib.sha256(b"apk").hexdigest(), result["sha256"])

    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as directory:
            value = Path(directory) / "value"
            value.write_bytes(b"caramel")
            self.assertEqual(hashlib.sha256(b"caramel").hexdigest(), sha256_file(value))


if __name__ == "__main__":
    unittest.main()
