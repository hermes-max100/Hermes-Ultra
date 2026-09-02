from hermes_ultra.trajectory_metrics import TrajectoryEvaluator


def action(kind, *, ok=True):
    return {"type": kind, "status": "success" if ok else "failed"}


def test_repetitive_failed_trajectory_flags_exploitation_error_and_reroute():
    ev = TrajectoryEvaluator()
    result = ev.evaluate([action("search", ok=False)] * 8)
    assert result.exploitation_error >= 0.75
    assert result.repetition_ratio >= 0.75
    assert result.adaptation == "reroute"


def test_broad_unproductive_exploration_flags_exploration_error():
    ev = TrajectoryEvaluator()
    actions = [action(f"tool-{i}", ok=False) for i in range(8)]
    result = ev.evaluate(actions)
    assert result.exploration_error >= 0.75
    assert result.adaptation == "narrow"


def test_productive_mixed_trajectory_continues_without_human_gate():
    ev = TrajectoryEvaluator()
    actions = [action("search"), action("read"), action("compute"), action("write"), action("verify")]
    result = ev.evaluate(actions)
    assert result.success_ratio == 1.0
    assert result.adaptation == "continue"
    payload = result.to_dict()
    assert "entropy_bits" in payload and "lz_complexity" in payload
