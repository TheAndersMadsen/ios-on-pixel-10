#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("inventory", Path(__file__).with_name("ios_app_inventory.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source, self.root = (Path(self.tmp.name) / s for s in ("source", "root"))
        for path in (self.source / "Applications", self.source / "private/var/staged_system_apps",
                     self.root / "Applications"):
            path.mkdir(parents=True)

    def app(self, parent, name="Clock", identifier="example.clock", executable="Clock"):
        app = parent / (name + ".app")
        app.mkdir()
        (app / "Info.plist").write_bytes(plistlib.dumps(dict(
            CFBundleIdentifier=identifier, CFBundleExecutable=executable)))
        (app / "Clock").write_bytes(b"fixture")
        return app

    def test_missing_apps_remain_in_manifest_and_never_count_as_launched(self):
        self.app(self.source / "private/var/staged_system_apps")
        report = module.inventory(self.source, self.root)
        self.assertEqual(report["summary"]["staged_bundles_absent"], 1)
        self.assertEqual(report["apps"][0]["runtime_launch"], "untested")
        self.assertEqual(module.registration_manifest(report)["apps"], [
            {"bundle_id": "example.clock", "path": "/Applications/Clock.app"}])

    def test_partial_bundle_is_not_complete(self):
        app = self.app(self.source / "private/var/staged_system_apps")
        (app / "Assets.car").write_bytes(b"artwork")
        self.app(self.root / "Applications")
        report = module.inventory(self.source, self.root)
        self.assertTrue(report["apps"][0]["executable_present"])
        self.assertEqual(report["apps"][0]["absent_regular_files"], 1)
        self.assertEqual(report["apps"][0]["absent_regular_bytes"], 7)

    def test_mismatched_identity_is_an_error(self):
        self.app(self.source / "private/var/staged_system_apps")
        self.app(self.root / "Applications", identifier="example.other")
        self.assertEqual(module.inventory(self.source, self.root)["summary"]["inventory_errors"], 1)

    def test_manifest_does_not_register_service_apps_by_default(self):
        self.app(self.source / "Applications", identifier="example.service")
        self.app(self.source / "private/var/staged_system_apps", name="Notes")
        report = module.inventory(self.source, self.root)
        self.assertEqual(len(module.registration_manifest(report)["apps"]), 1)
        with self.assertRaises(ValueError):
            module.registration_manifest(report, ["example.unknown"])

    def test_executable_traversal_is_refused(self):
        self.app(self.source / "private/var/staged_system_apps", executable="../Clock")
        report = module.inventory(self.source, self.root)
        self.assertEqual(report["summary"]["inventory_errors"], 1)
        with self.assertRaises(ValueError):
            module.registration_manifest(report)

    def test_bundle_symlink_is_not_treated_as_installed_content(self):
        app = self.app(self.source / "private/var/staged_system_apps")
        (self.root / "Applications/Clock.app").symlink_to(app, target_is_directory=True)
        row = module.inventory(self.source, self.root)["apps"][0]
        self.assertFalse(row["bundle_present"])
        self.assertFalse(row["executable_present"])

    def test_absent_stock_tree_cannot_be_misreported_as_zero_apps(self):
        (self.source / "private/var/staged_system_apps").rmdir()
        with self.assertRaises(ValueError):
            module.inventory(self.source, self.root)


if __name__ == "__main__":
    unittest.main()
