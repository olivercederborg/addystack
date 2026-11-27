"""Tests for kit_path.py, which finds the ADDYSTACK_KIT checkout the maintainer scripts and
the pre-commit read."""
import os
import tempfile
import unittest
from unittest import mock

import kit_path


class KitPathTest(unittest.TestCase):
    def test_a_folder_without_the_tool_is_refused_naming_the_setting(self):
        with tempfile.TemporaryDirectory() as empty, mock.patch.dict(os.environ, {"ADDYSTACK_KIT": empty}):
            with self.assertRaises(SystemExit) as raised:
                kit_path.repo()
        self.assertIn("ADDYSTACK_KIT", str(raised.exception))

    def test_the_setting_picks_the_checkout(self):
        kit = kit_path.repo()
        with mock.patch.dict(os.environ, {"ADDYSTACK_KIT": str(kit)}):
            self.assertEqual(kit_path.tool(), kit / "skills/primitive/addystack")
            self.assertEqual(kit_path.skill("correct"), kit / "skills/primitive/correct")


if __name__ == "__main__":
    unittest.main()
