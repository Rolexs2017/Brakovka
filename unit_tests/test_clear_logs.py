"""Unit tests for journal log clearing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from brakovka_pi.logutil import ERROR_LOG_NAME, INFO_LOG_NAME, clear_log_files


class TestClearLogFiles(unittest.TestCase):
    def test_truncates_active_and_deletes_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / INFO_LOG_NAME).write_text("a\n", encoding="utf-8")
            (d / ERROR_LOG_NAME).write_text("b\n", encoding="utf-8")
            (d / f"{INFO_LOG_NAME}.1").write_text("old\n", encoding="utf-8")
            touched, errors = clear_log_files(d)
            self.assertEqual(errors, [])
            self.assertEqual(touched, 3)
            self.assertEqual((d / INFO_LOG_NAME).read_text(encoding="utf-8"), "")
            self.assertEqual((d / ERROR_LOG_NAME).read_text(encoding="utf-8"), "")
            self.assertFalse((d / f"{INFO_LOG_NAME}.1").exists())


if __name__ == "__main__":
    unittest.main()
