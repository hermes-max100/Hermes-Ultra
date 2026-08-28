#!/usr/bin/env python3
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/system/containment-gateway.py"
spec = importlib.util.spec_from_file_location("containment_gateway", MODULE_PATH)
cg = importlib.util.module_from_spec(spec)
assert spec.loader
sys.modules[spec.name] = cg
spec.loader.exec_module(cg)

SECRET = "test-secret-that-is-longer-than-thirty-two-bytes"
NOW = datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)


class ContainmentGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name) / "state"
        self.scope = cg.RequestScope.make(
            "agent:hermes", "mcp:github", "https://api.github.com",
            "repo:hurakan100/Hermes-Evolution", "INTERNAL",
        )

    def tearDown(self):
        self.temp.cleanup()

    def token(self, **kwargs):
        return cg.issue_capability(
            secret=SECRET,
            scope=kwargs.pop("scope", self.scope),
            purpose="repo-maintenance",
            evidence_id="ev_123",
            ttl_seconds=kwargs.pop("ttl_seconds", 60),
            now=kwargs.pop("now", NOW),
            grant_id=kwargs.pop("grant_id", "cap_test"),
            **kwargs,
        )

    def verify(self, token=None, scope=None, **kwargs):
        return cg.verify_capability(
            token=token or self.token(), secret=SECRET, requested=scope or self.scope,
            state_dir=self.state, now=kwargs.pop("now", NOW + timedelta(seconds=1)), **kwargs,
        )

    def assertDenied(self, reason, fn):
        with self.assertRaises(cg.CapabilityError) as ctx:
            fn()
        self.assertEqual(reason, str(ctx.exception))

    def resign(self, token):
        token["signature"]["value"] = cg.sign(token["body"], SECRET)
        return token

    def test_valid_exact_scope_allows_and_emits_receipt(self):
        receipt = self.verify()
        self.assertEqual("ALLOW", receipt["decision"])
        self.assertEqual("https://api.github.com", receipt["destination"])
        self.assertNotIn("secret", json.dumps(receipt).lower())

    def test_destination_scope_is_exact(self):
        other = cg.RequestScope.make(
            "agent:hermes", "mcp:github", "https://example.com", self.scope.resource, "INTERNAL"
        )
        self.assertDenied("scope_mismatch:destination", lambda: self.verify(scope=other))

    def test_resource_scope_is_exact(self):
        other = cg.RequestScope.make(
            "agent:hermes", "mcp:github", self.scope.destination, "repo:other/repo", "INTERNAL"
        )
        self.assertDenied("scope_mismatch:resource", lambda: self.verify(scope=other))

    def test_principal_and_tool_are_bound(self):
        other = cg.RequestScope.make(
            "agent:scout", "browser", self.scope.destination, self.scope.resource, "INTERNAL"
        )
        self.assertDenied("scope_mismatch:principal,tool", lambda: self.verify(scope=other))

    def test_expired_capability_denies(self):
        self.assertDenied(
            "capability_expired", lambda: self.verify(now=NOW + timedelta(seconds=61))
        )

    def test_tamper_denies(self):
        token = self.token()
        token["body"]["resource"] = "repo:attacker/repo"
        self.assertDenied("invalid_signature", lambda: self.verify(token=token))

    def test_single_use_replay_denies(self):
        token = self.token()
        self.verify(token=token)
        self.assertDenied("capability_replay", lambda: self.verify(token=token))

    def test_revocation_denies(self):
        token = self.token()
        cg.revoke(self.state, "cap_test", "operator")
        self.assertDenied("capability_revoked", lambda: self.verify(token=token))

    def test_kill_switch_denies_even_valid_capability(self):
        cg.set_kill_switch(self.state, True, "incident")
        self.assertDenied("containment_kill_switch_active", lambda: self.verify())

    def test_kill_on_does_not_depend_on_ttl_configuration(self):
        env = {
            "HERMES_CONTAINMENT_STATE_DIR": str(self.state),
            "HERMES_CONTAINMENT_MAX_TTL": "invalid-ttl",
        }
        with patch.dict(os.environ, env, clear=False):
            rc = cg.main(["kill", "on", "--reason", "incident"])
        self.assertEqual(0, rc)
        self.assertTrue((self.state / "KILL_SWITCH").is_file())

    def test_ttl_is_bounded(self):
        self.assertDenied("ttl_out_of_policy", lambda: self.token(ttl_seconds=301))

    def test_verifier_independently_rejects_oversized_signed_window(self):
        token = self.token(ttl_seconds=600, max_ttl_seconds=600)
        self.assertDenied(
            "capability_ttl_exceeds_verifier_policy",
            lambda: self.verify(token=token),
        )

    def test_short_secret_denies(self):
        self.assertDenied(
            "containment_secret_missing_or_too_short",
            lambda: cg.issue_capability(
                secret="short", scope=self.scope, purpose="x", evidence_id="ev",
                ttl_seconds=10, now=NOW,
            ),
        )

    def test_grant_id_rejects_path_traversal(self):
        self.assertDenied(
            "invalid_grant_id",
            lambda: self.token(grant_id="../../escape"),
        )
        self.assertDenied(
            "invalid_grant_id",
            lambda: cg.revoke(self.state, "../escape", "operator"),
        )

    def test_destination_rejects_path_and_embedded_credentials(self):
        self.assertDenied(
            "destination_must_be_origin_only",
            lambda: cg.canonical_destination("https://api.github.com/repos/x"),
        )
        self.assertDenied(
            "invalid_destination", lambda: cg.canonical_destination("https://u:p@example.com")
        )

    def test_destination_ipv6_is_canonical_and_unambiguous(self):
        self.assertEqual(
            "https://[2001:db8::1]",
            cg.canonical_destination("https://[2001:db8::1]"),
        )
        self.assertEqual(
            "https://[2001:db8::1]:8443",
            cg.canonical_destination("https://[2001:db8::1]:8443"),
        )

    def test_cloud_metadata_ip_literals_are_forbidden(self):
        self.assertDenied(
            "forbidden_destination_ip",
            lambda: cg.canonical_destination("http://169.254.169.254"),
        )
        self.assertDenied(
            "forbidden_destination_ip",
            lambda: cg.canonical_destination("http://[fd00:ec2::254]"),
        )

    def test_state_dir_symlink_is_rejected(self):
        real_state = Path(self.temp.name) / "real-state"
        real_state.mkdir(mode=0o700)
        linked_state = Path(self.temp.name) / "linked-state"
        linked_state.symlink_to(real_state, target_is_directory=True)
        self.assertDenied(
            "unsafe_state_dir_symlink",
            lambda: cg.verify_capability(
                token=self.token(), secret=SECRET, requested=self.scope,
                state_dir=linked_state, now=NOW + timedelta(seconds=1),
            ),
        )

    def test_signed_unknown_fields_are_rejected(self):
        token = self.token()
        token["body"]["future_policy_override"] = "allow"
        self.resign(token)
        self.assertDenied("capability_unknown_fields", lambda: self.verify(token=token))

    def test_single_use_requires_boolean_type(self):
        token = self.token()
        token["body"]["single_use"] = 0
        self.resign(token)
        self.assertDenied("invalid_single_use_type", lambda: self.verify(token=token))

    def test_token_file_symlink_and_oversize_are_rejected(self):
        token_file = Path(self.temp.name) / "token.json"
        token_file.write_text(json.dumps(self.token()), encoding="utf-8")
        token_link = Path(self.temp.name) / "token-link.json"
        token_link.symlink_to(token_file)
        self.assertDenied(
            "token_file_symlink_forbidden", lambda: cg.load_json(str(token_link))
        )

        oversized = Path(self.temp.name) / "oversized.json"
        oversized.write_text(json.dumps({"pad": "x" * 70000}), encoding="utf-8")
        self.assertDenied("token_file_too_large", lambda: cg.load_json(str(oversized)))

    def test_cli_verify_uses_stdin_not_caller_selected_file_path(self):
        verify_scope = [
            "--principal", "agent:hermes", "--tool", "mcp:github",
            "--destination", "https://api.github.com", "--resource", self.scope.resource,
            "--data-class", "INTERNAL",
        ]
        with self.assertRaises(SystemExit):
            cg.parser().parse_args(["verify", "--token", "/etc/passwd", *verify_scope])
        args = cg.parser().parse_args(["verify", "--token-stdin", *verify_scope])
        self.assertTrue(args.token_stdin)

    def test_cli_does_not_expose_trusted_configuration_bypass_flags(self):
        valid_issue = [
            "issue", "--principal", "agent:hermes", "--tool", "mcp:github",
            "--destination", "https://api.github.com", "--resource", self.scope.resource,
            "--data-class", "INTERNAL", "--purpose", "repo-maintenance",
            "--evidence-id", "ev_cli",
        ]
        dangerous_argv = [
            ["--secret-env", "PATH", *valid_issue],
            ["--state-dir", "/tmp/fresh", "status"],
            [*valid_issue, "--multi-use"],
            [*valid_issue, "--max-ttl", "999999"],
            [
                "verify", "--token-stdin", "--principal", "agent:hermes",
                "--tool", "mcp:github", "--destination", "https://api.github.com",
                "--resource", self.scope.resource, "--data-class", "INTERNAL",
                "--no-consume",
            ],
        ]
        for argv in dangerous_argv:
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit):
                    cg.parser().parse_args(argv)


if __name__ == "__main__":
    unittest.main(verbosity=2)
