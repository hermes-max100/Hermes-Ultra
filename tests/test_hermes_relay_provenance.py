import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class RelayProvenanceTests(unittest.TestCase):
    def test_android_pin_is_1_13_2(self):
        versions = load_json("config/production-versions.json")
        relay = versions["hermes_relay_android"]
        self.assertEqual(relay["tag"], "android-v1.13.2")
        self.assertEqual(relay["version"], "1.13.2")
        self.assertEqual(versions["frozen_at"], "2026-08-28")

    def test_components_are_independently_pinned(self):
        manifest = load_json("config/hermes-relay-upstream.json")
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(
            manifest["android"]["commit"],
            "a5cc0104bfbda8542667ab50eb70ab02b02a47e5",
        )
        self.assertEqual(
            manifest["server"]["commit"],
            "08545ed32db07609c14730a7fc02cdd758f12434",
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
            "android": "ee301ab1cdcaa9255b1c81899ee0719ed842603f2b6e05ce9dd1a8861df6391d",
            "server": "26d3e7791cdadcd162157ddd593379b8f872032eb247611336dddf1f180e4663",
            "desktop": "2ff381b9a7d501146d77b44cb25d6d4c987c677c3b550cad6f1b766c08631110",
        }
        for component, digest in expected.items():
            self.assertEqual(manifest[component]["artifact_sha256"], digest)
            self.assertEqual(manifest[component]["license"], "MIT")


if __name__ == "__main__":
    unittest.main()
