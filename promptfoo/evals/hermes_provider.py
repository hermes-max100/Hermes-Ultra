import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _messages_to_query(prompt):
    if isinstance(prompt, list):
        for message in reversed(prompt):
            if isinstance(message, dict) and message.get("role") == "user":
                return message.get("content", "")
        return json.dumps(prompt)
    if not isinstance(prompt, str):
        return str(prompt)
    try:
        parsed = json.loads(prompt)
    except json.JSONDecodeError:
        return prompt
    if isinstance(parsed, list):
        return _messages_to_query(parsed)
    return prompt


def _prompt_text(prompt):
    if isinstance(prompt, str):
        return prompt
    return json.dumps(prompt, ensure_ascii=False)


def call_api(prompt, options, context):
    vars_ = context.get("vars", {})
    query = _messages_to_query(prompt) or vars_.get("query", "")
    profile = vars_.get("profile", "direct")
    expected_model = vars_.get("expected_model") or vars_.get("model")

    if vars_.get("eval_driver") == "revenue-ops-compliance":
        result = subprocess.run(
            [
                str(ROOT / "src/system/revenue-ops.sh"),
                "compliance-check",
                "--text",
                query,
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        return {
            "output": "\n".join(
                [
                    "=== DYNAMIC PROMPT ===",
                    _prompt_text(prompt),
                    "=== REVENUE OPS COMPLIANCE ===",
                    result.stdout,
                    f"exit_code={result.returncode}",
                ]
            )
        }

    env = os.environ.copy()
    if expected_model:
        env["HERMES_MODEL_OVERRIDE"] = expected_model
        if "kimi-k3" in expected_model:
            env["HERMES_MODEL_KEY_OVERRIDE"] = "ninerouter-gateway"
            env["HERMES_PROVIDER_OVERRIDE"] = "9router"

    cmd = [
        str(ROOT / "src/system/hermes-dispatch.sh"),
        "--profile",
        profile,
        "--report",
        query,
    ]
    if vars_.get("project"):
        cmd.insert(2, "--project")
        cmd.insert(3, vars_["project"])

    result = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    return {
        "output": "\n".join(
            [
                "=== DYNAMIC PROMPT ===",
                _prompt_text(prompt),
                "=== HERMES ROUTE ===",
                result.stdout,
                f"exit_code={result.returncode}",
            ]
        )
    }
