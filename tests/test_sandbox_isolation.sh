#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXECUTOR="$ROOT_DIR/src/system/sandbox-candidate-executor.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

export HERMES_MEMORY_DISABLE=1
export HERMES_TRUST_GATE_REPORTS_DIR="$TMP_DIR/trust-gate"
export HERMES_TRUST_GATE_CACHE_DIR="$TMP_DIR/trust-cache"

package_dir="$TMP_DIR/candidate"
mkdir -p "$package_dir"

cat > "$TMP_DIR/escape.patch" <<'PATCH'
diff --git a/sandbox-isolation-probe.py b/sandbox-isolation-probe.py
new file mode 100644
--- /dev/null
+++ b/sandbox-isolation-probe.py
@@ -0,0 +1,33 @@
+from pathlib import Path
+import errno
+import socket
+import sys
+
+# The sandbox must deny creation of network sockets at the syscall boundary.
+try:
+    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
+except OSError as exc:
+    if exc.errno != errno.EPERM:
+        raise
+else:
+    sock.close()
+    print("network escape: AF_INET socket creation succeeded", file=sys.stderr)
+    raise SystemExit(41)
+
+# A detached Git worktree is not enough: candidate code must not be able to
+# write outside its assigned workspace.
+escape = Path.cwd().parent / "candidate-escape.txt"
+try:
+    escape.write_text("escaped\n", encoding="utf-8")
+except OSError:
+    pass
+else:
+    print(f"filesystem escape: {escape}", file=sys.stderr)
+    raise SystemExit(42)
+
+# The disposable workspace itself must remain writable for candidate tests.
+inside = Path("sandbox-write-ok.txt")
+inside.write_text("ok\n", encoding="utf-8")
+if inside.read_text(encoding="utf-8") != "ok\n":
+    raise SystemExit(43)
+
+print("sandbox isolation enforced")
PATCH

python3 - "$package_dir" "$TMP_DIR/escape.patch" <<'PY'
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

package_dir = pathlib.Path(sys.argv[1])
patch_text = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")

def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

def sha_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

def sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

regression = {
    "artifact_type": "candidate-regression-test-spec",
    "source_cluster_id": "cluster_sandbox_escape",
    "root_signature_hash": "root_sandbox_escape",
    "source_trajectory_ids": ["traj_sandbox_escape"],
    "test_objective": "Prove candidate code cannot create network sockets or write outside workspace",
    "fixtures": [],
    "assertions": ["AF_INET socket returns EPERM", "no write outside workspace"],
    "commands": ["python3 sandbox-isolation-probe.py"],
    "created_before_candidate_spec": True,
    "created_at": now(),
}
regression_path = package_dir / "regression-test-spec.json"
regression_path.write_text(json.dumps(regression, indent=2, sort_keys=True) + "\n", encoding="utf-8")
regression_hash = sha_file(regression_path)
manifest = {
    "artifact_type": "hermes-candidate-package", "candidate_id": "cand_sandbox_escape",
    "generation_nonce": now(), "source_cluster_id": "cluster_sandbox_escape",
    "root_signature_hash": "root_sandbox_escape", "root_signature": {"failure_class": "sandbox_escape"},
    "source_trajectory_ids": ["traj_sandbox_escape"], "source_evidence_hashes": ["sha256:sandbox-escape"],
    "causal_hypothesis": "Candidate tests require OS containment, not command filtering.",
    "hypothesis_confidence": 1.0, "target_component": "sandbox-candidate-executor",
    "change_type": "bounded_candidate_patch", "affected_paths": ["sandbox-isolation-probe.py"],
    "affected_files_or_skills": [], "base_version_hashes": {},
    "proposed_diff": {"format": "unified_diff", "content": patch_text, "status": "explicit_patch"},
    "candidate_implementation": {"mode": "explicit_patch"}, "new_regression_tests": [str(regression_path)],
    "expected_improvement": "Sandbox blocks network syscalls and host filesystem escape.",
    "possible_regressions": [], "security_classification": "INTERNAL", "risk_class": "critical",
    "existing_anchor_ids": [], "required_anchor_changes": [], "benchmark_gap_proposal": None,
    "generator_model": "red-team-fixture", "generator_version": "1", "generated_at": now(),
    "candidate_manifest_hash_scope": "sha256_json over canonical manifest JSON with candidate_manifest_hash omitted",
    "regression_test_spec_hash": regression_hash, "governance_boundaries": ["test fixture"],
}
manifest["candidate_manifest_hash"] = sha_json(manifest)
manifest_path = package_dir / "candidate-manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
receipt = {
    "artifact_type": "candidate-package-receipt", "candidate_id": manifest["candidate_id"],
    "source_cluster_id": manifest["source_cluster_id"], "candidate_manifest_path": str(manifest_path),
    "candidate_manifest_hash": manifest["candidate_manifest_hash"], "candidate_manifest_hash_scope": manifest["candidate_manifest_hash_scope"],
    "regression_test_spec_path": str(regression_path), "regression_test_spec_hash": regression_hash,
    "created_at": now(), "package_immutable": True,
}
(package_dir / "candidate-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

output="$($EXECUTOR "$package_dir" --sandbox-dir "$TMP_DIR/worktrees" --result-dir "$TMP_DIR/results" --governance-test "bash -n src/system/candidate-generator.sh")"
result_path="$(python3 - "$output" <<'PY'
import json, sys
print(json.loads(sys.argv[1])["sandbox_result_path"])
PY
)"
if [[ "$output" != *'"status": "sandbox_passed"'* ]]; then
  cat "$result_path" >&2
  echo "$output" >&2
  exit 1
fi
if find "$TMP_DIR/worktrees" -name candidate-escape.txt | grep -q .; then
  echo "candidate wrote outside its workspace" >&2
  exit 1
fi
if ! grep -q 'sandbox isolation enforced' "$result_path"; then
  # stdout is redacted to excerpts/hashes in the result; verify the candidate
  # regression command succeeded instead of requiring raw output retention.
  python3 - "$result_path" <<'PY'
import json, sys
obj = json.load(open(sys.argv[1], encoding="utf-8"))
rows = [r for r in obj["test_results"] if r.get("phase") == "candidate_regression"]
assert rows and rows[0]["returncode"] == 0, rows
PY
fi

echo "sandbox isolation tests passed"
