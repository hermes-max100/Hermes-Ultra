#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXECUTOR="$ROOT_DIR/src/system/sandbox-candidate-executor.sh"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

export HERMES_MEMORY_DB="$TMP_DIR/memory.sqlite3"
export HERMES_TRUST_GATE_REPORTS_DIR="$TMP_DIR/trust-gate"
export HERMES_TRUST_GATE_CACHE_DIR="$TMP_DIR/trust-cache"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "Expected output to contain: $needle" >&2
    echo "$haystack" >&2
    exit 1
  fi
}

make_package() {
  local package_dir="$1"
  local patch_file="$2"
  local affected_path="$3"
  local candidate_id="$4"
  mkdir -p "$package_dir"
  python3 - "$package_dir" "$patch_file" "$affected_path" "$candidate_id" <<'PY'
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

package_dir = pathlib.Path(sys.argv[1])
patch_text = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
affected_path = sys.argv[3]
candidate_id = sys.argv[4]

def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

def sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def sha_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

regression = {
    "artifact_type": "candidate-regression-test-spec",
    "source_cluster_id": "cluster_executor_test",
    "root_signature_hash": "root_executor_test",
    "source_trajectory_ids": ["traj_executor_test"],
    "test_objective": "Verify sandbox patch application",
    "fixtures": [],
    "assertions": ["fixture file exists after patch"],
    "commands": ["test -f sandbox-fixture.txt && grep -q sandbox-candidate sandbox-fixture.txt"],
    "created_before_candidate_spec": True,
    "created_at": now(),
}
regression_path = package_dir / "regression-test-spec.json"
regression_path.write_text(json.dumps(regression, indent=2, sort_keys=True) + "\n", encoding="utf-8")
regression_hash = sha_file(regression_path)
manifest = {
    "artifact_type": "hermes-candidate-package", "candidate_id": candidate_id, "generation_nonce": now(),
    "source_cluster_id": "cluster_executor_test", "root_signature_hash": "root_executor_test",
    "root_signature": {"failure_class": "sandbox-fixture"}, "source_trajectory_ids": ["traj_executor_test"],
    "source_evidence_hashes": ["sha256:executor-fixture"], "causal_hypothesis": "Fixture failure is resolved by adding a file.",
    "hypothesis_confidence": 0.8, "target_component": "sandbox-fixture", "change_type": "bounded_candidate_patch",
    "affected_paths": [affected_path], "affected_files_or_skills": [], "base_version_hashes": {},
    "proposed_diff": {"format": "unified_diff", "content": patch_text, "status": "explicit_patch"},
    "candidate_implementation": {"mode": "explicit_patch"}, "new_regression_tests": [str(regression_path)],
    "expected_improvement": "Sandbox fixture passes.", "possible_regressions": [], "security_classification": "INTERNAL",
    "risk_class": "medium", "existing_anchor_ids": [], "required_anchor_changes": [], "benchmark_gap_proposal": None,
    "generator_model": "test-fixture", "generator_version": "test-fixture", "generated_at": now(),
    "candidate_manifest_hash_scope": "sha256_json over canonical manifest JSON with candidate_manifest_hash omitted",
    "regression_test_spec_hash": regression_hash, "governance_boundaries": ["test fixture"],
}
manifest["candidate_manifest_hash"] = sha_json(manifest)
manifest_path = package_dir / "candidate-manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
receipt = {
    "artifact_type": "candidate-package-receipt", "candidate_id": candidate_id,
    "source_cluster_id": "cluster_executor_test", "candidate_manifest_path": str(manifest_path),
    "candidate_manifest_hash": manifest["candidate_manifest_hash"], "candidate_manifest_hash_scope": manifest["candidate_manifest_hash_scope"],
    "regression_test_spec_path": str(regression_path), "regression_test_spec_hash": regression_hash,
    "created_at": now(), "package_immutable": True,
}
(package_dir / "candidate-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

cat > "$TMP_DIR/safe.patch" <<'EOF'
diff --git a/sandbox-fixture.txt b/sandbox-fixture.txt
new file mode 100644
index 0000000..4313ad0
--- /dev/null
+++ b/sandbox-fixture.txt
@@ -0,0 +1 @@
+sandbox-candidate
EOF

safe_package="$TMP_DIR/candidates/cand_executor_safe"
make_package "$safe_package" "$TMP_DIR/safe.patch" "sandbox-fixture.txt" "cand_executor_safe"
safe_output="$("$EXECUTOR" "$safe_package" --sandbox-dir "$TMP_DIR/worktrees" --result-dir "$TMP_DIR/results" --governance-test "bash -n src/system/candidate-generator.sh")"
if [[ "$safe_output" != *'"status": "sandbox_passed"'* ]]; then
  safe_result_path="$(python3 - "$safe_output" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("sandbox_result_path", ""))
PY
)"
  [[ -n "$safe_result_path" && -f "$safe_result_path" ]] && cat "$safe_result_path" >&2
  echo "$safe_output" >&2
  exit 1
fi
assert_contains "$safe_output" '"sandbox_result_hash"'
assert_contains "$safe_output" '"memory_status": "persisted"'

safe_result="$(python3 - "$safe_output" <<'PY'
import json, sys
print(json.loads(sys.argv[1])["sandbox_result_path"])
PY
)"
safe_patch="$(python3 - "$safe_output" <<'PY'
import json, sys
print(json.loads(sys.argv[1])["patch_path"])
PY
)"
test -f "$safe_result"
test -f "$safe_patch"
assert_contains "$(cat "$safe_result")" '"actual_affected_paths": ['
assert_contains "$(cat "$safe_result")" '"sandbox-fixture.txt"'
assert_contains "$(cat "$safe_result")" '"status": "sandbox_passed"'

if [[ -e "$ROOT_DIR/sandbox-fixture.txt" ]]; then
  echo "sandbox executor mutated the live checkout" >&2
  exit 1
fi

cat > "$TMP_DIR/protected.patch" <<'EOF'
diff --git a/src/system/trust-gate.py b/src/system/trust-gate.py
--- a/src/system/trust-gate.py
+++ b/src/system/trust-gate.py
@@ -1,2 +1,3 @@
 #!/usr/bin/env python3
+# unauthorized governance edit
 """Hermes Trust Gate.
EOF

protected_package="$TMP_DIR/candidates/cand_executor_protected"
make_package "$protected_package" "$TMP_DIR/protected.patch" "src/system/trust-gate.py" "cand_executor_protected"
protected_output="$("$EXECUTOR" "$protected_package" --sandbox-dir "$TMP_DIR/worktrees" --result-dir "$TMP_DIR/results" --governance-test "bash -n src/system/candidate-generator.sh")"
assert_contains "$protected_output" '"status": "sandbox_failed"'
protected_result="$(python3 - "$protected_output" <<'PY'
import json, sys
print(json.loads(sys.argv[1])["sandbox_result_path"])
PY
)"
assert_contains "$(cat "$protected_result")" "candidate patch touches protected governance paths"

# The public execution boundary must reject request-time governance bypass.
if "$EXECUTOR" "$protected_package" --sandbox-dir "$TMP_DIR/worktrees2" --result-dir "$TMP_DIR/results2" --allow-governance-paths >/dev/null 2>&1; then
  echo "expected --allow-governance-paths to be rejected" >&2
  exit 1
fi

echo "sandbox candidate executor tests passed"
