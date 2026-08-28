# Hermes Sandbox Candidate Executor v1

`src/system/sandbox-candidate-executor.sh` executes an explicit candidate patch
inside a disposable detached Git worktree and emits an immutable sandbox result
bundle.

It is not a promoter.

```text
candidate package
-> verify manifest / receipt / regression hashes
-> detached worktree
-> apply explicit bounded patch
-> candidate regression
-> affected subsystem tests
-> mandatory governance regressions
-> immutable sandbox result
-> Memory Fabric evidence
-> Trust Gate handoff
```

## Command

```bash
src/system/sandbox-candidate-executor.sh .hermes/candidates/cand_<id> \
  --subsystem-test "bash tests/test_relevant_subsystem.sh"
```

By default it also runs mandatory governance regressions:

- `bash tests/test_memory_fabric.sh`
- `bash tests/test_trajectory_fabric.sh`
- `bash tests/test_memory_classification.sh`
- `bash tests/test_anchor_evaluator.sh`
- `bash tests/test_canary_controller.sh`
- `bash tests/test_trust_gate.sh`

## Security Model

The executor:

- verifies `candidate-manifest.json`, `candidate-receipt.json`, and
  `regression-test-spec.json`
- requires `required_anchor_changes == []`
- verifies candidate manifest and regression hashes
- pins execution to a base Git commit
- creates a detached disposable worktree
- strips credential-bearing environment variables
- rejects common network-capable commands in sandbox tests
- requires patch paths to be predeclared in `affected_paths`
- rejects scope escape
- rejects protected governance paths unless `--allow-governance-paths` is
  explicitly passed
- produces a patch and result bundle only

The network restriction is a command-policy default deny. Use a stronger
container, namespace, VM, or firewall wrapper for hostile candidates.

## Result Artifacts

Results are written under:

```text
.hermes/sandbox-results/sbox_<id>/
```

Each result bundle contains:

- `candidate.patch`
- `sandbox-result.json`
- `sandbox-receipt.json`

`sandbox-result.json` includes:

- `candidate_id`
- `sandbox_run_id`
- `input_manifest_hash`
- `base_commit`
- `base_file_hashes`
- `actual_affected_paths`
- `patch_hash`
- `regression_spec_hash`
- `test_results`
- `existing_suite_results`
- `stdout_stderr_hashes`
- `resource_usage`
- `security_findings`
- `exit_status`
- `sandbox_result_hash`

## Status Values

- `sandbox_passed`: explicit patch applied and all required tests passed
- `sandbox_failed`: patch, scope, protected-path, or test failure
- `sandbox_noop`: package did not contain explicit patch content

`sandbox_passed` is not validation or promotion. Trust Gate must inspect the
result package before Anchor Evaluator treats it as candidate implementation.

## Boundaries

The executor must not:

- edit the live checkout
- commit
- promote
- modify anchors or frozen success criteria
- modify routing/model policy
- weaken Trust Gate, Memory Fabric, Anchor Evaluator, Canary/Rollback, or
  approval policy

Protected governance changes require a separately governed candidate and an
explicit `--allow-governance-paths` run.
