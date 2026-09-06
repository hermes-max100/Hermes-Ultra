import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class RelayProvenanceTests(unittest.TestCase):
    def test_android_pin_is_current(self):
        versions = load_json("config/production-versions.json")
        relay = versions["hermes_relay_android"]
        self.assertEqual(relay["tag"], "android-v1.15.1")
        self.assertEqual(relay["version"], "1.15.1")
        self.assertEqual(versions["frozen_at"], "2026-09-05")

    def test_components_are_independently_pinned(self):
        manifest = load_json("config/hermes-relay-upstream.json")
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(
            manifest["android"]["commit"],
            "75feb55adfa898af118c078f8d1cf9a72b99682b",
        )
        self.assertEqual(
            manifest["server"]["commit"],
            "f4b366389ba8081136e81ca1b76deb31ef844cce",
        )
        self.assertEqual(
            manifest["desktop"]["commit"],
            "8acba9b3539a1905fc7361efcab97de8199a0ac9",
        )
        self.assertNotEqual(
            manifest["android"]["version"], manifest["server"]["version"]
        )

    def test_artifacts_and_licenses_are_exact(self):
        manifest = load_json("config/hermes-relay-upstream.json")
        expected = {
            "android": "1d45261f48184225a070a7d05ae6ed4e44b2b9ae6e8d1e3fbe941fe9097d84d3",
            "server": "251342d4ddd9d0e55563f9185850764cf5f43200d54c120c6719329f311e76a0",
            "desktop": "2ff381b9a7d501146d77b44cb25d6d4c987c677c3b550cad6f1b766c08631110",
        }
        for component, digest in expected.items():
            self.assertEqual(manifest[component]["artifact_sha256"], digest)
            self.assertEqual(manifest[component]["license"], "MIT")


if __name__ == "__main__":
    unittest.main()
