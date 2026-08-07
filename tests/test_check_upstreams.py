from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from check_upstreams import find_updates, render_report


class UpstreamCheckTest(unittest.TestCase):
    def setUp(self):
        self.packages = {
            "com.example.app": {
                "display_name": "Example",
                "repository": "example/app",
                "branch": "main",
                "last_reviewed_commit": "a" * 40,
                "review_notes": "Run the release tests.",
            }
        }

    @patch("check_upstreams.fetch_branch_head")
    def test_reports_moved_branch(self, fetch):
        fetch.return_value = {
            "sha": "b" * 40,
            "html_url": "https://github.com/example/app/commit/" + "b" * 40,
        }
        updates = find_updates(self.packages)
        self.assertEqual("b" * 40, updates[0]["head_commit"])
        report = render_report(updates)
        self.assertIn("Nothing is built or published automatically", report)
        self.assertIn("Run the release tests", report)

    @patch("check_upstreams.fetch_branch_head")
    def test_ignores_reviewed_head(self, fetch):
        fetch.return_value = {
            "sha": "a" * 40,
            "html_url": "https://github.com/example/app/commit/" + "a" * 40,
        }
        self.assertEqual([], find_updates(self.packages))
        self.assertIn("No tracked upstream", render_report([]))


if __name__ == "__main__":
    unittest.main()
