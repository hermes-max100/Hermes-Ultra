import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class DesktopRelayPinTests(unittest.TestCase):
    def test_desktop_beta_is_immutable_and_complete(self):
        data=json.loads((ROOT/'config/hermes-relay-upstream.json').read_text())['desktop']
        self.assertEqual(data['tag'],'desktop-v0.4.0-beta.5')
        self.assertEqual(data['version'],'0.4.0-beta.5')
        self.assertEqual(data['commit'],'8acba9b3539a1905fc7361efcab97de8199a0ac9')
        self.assertEqual(data['artifact'],'hermes-relay-linux-x64')
        self.assertEqual(data['artifact_sha256'],'2ff381b9a7d501146d77b44cb25d6d4c987c677c3b550cad6f1b766c08631110')
        self.assertIs(data['prerelease'], True)
        self.assertEqual(data['license'],'MIT')
        for key in ('tag','version','commit','artifact','artifact_sha256','source_url','license'):
            self.assertTrue(str(data[key]).strip(), key)

if __name__ == '__main__': unittest.main(verbosity=2)
