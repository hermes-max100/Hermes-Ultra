from __future__ import annotations

from types import SimpleNamespace

import pytest

from hermes_ultra.agent_reach import (
    SUPPORTED_CHANNELS,
    AgentReachAdapter,
    AgentReachError,
)


def fake_run_factory(returncode=0, stdout="ok", stderr=""):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return calls, fake_run


def test_all_supported_optional_channels_are_declared():
    assert SUPPORTED_CHANNELS == (
        "opencli",
        "twitter",
        "xiaoyuzhou",
        "xueqiu",
        "xiaohongshu",
        "reddit",
        "facebook",
        "instagram",
        "bilibili",
        "linkedin",
    )


def test_install_all_check_only(monkeypatch):
    calls, fake_run = fake_run_factory()
    monkeypatch.setattr("hermes_ultra.agent_reach.subprocess.run", fake_run)
    adapter = AgentReachAdapter(env={"PATH": "/bin"})

    result = adapter.install_all()

    assert result.ok
    assert calls[0][0] == [
        "agent-reach",
        "install",
        "--env=auto",
        "--channels=all",
    ]


def test_install_all_system_mode(monkeypatch):
    calls, fake_run = fake_run_factory()
    monkeypatch.setattr("hermes_ultra.agent_reach.subprocess.run", fake_run)
    adapter = AgentReachAdapter(env={"PATH": "/bin"})

    adapter.install_all(system=True)

    assert calls[0][0][-1] == "--system"


def test_install_all_dry_run_takes_precedence(monkeypatch):
    calls, fake_run = fake_run_factory()
    monkeypatch.setattr("hermes_ultra.agent_reach.subprocess.run", fake_run)
    adapter = AgentReachAdapter(env={"PATH": "/bin"})

    adapter.install_all(system=True, dry_run=True)

    assert calls[0][0][-1] == "--dry-run"
    assert "--system" not in calls[0][0]


def test_doctor_returns_failure_as_evidence(monkeypatch):
    calls, fake_run = fake_run_factory(returncode=3, stderr="twitter missing")
    monkeypatch.setattr("hermes_ultra.agent_reach.subprocess.run", fake_run)
    adapter = AgentReachAdapter(env={"PATH": "/bin"})

    result = adapter.doctor()

    assert not result.ok
    assert result.returncode == 3
    assert "twitter missing" in result.stderr


def test_regular_failure_raises(monkeypatch):
    calls, fake_run = fake_run_factory(returncode=2, stderr="boom")
    monkeypatch.setattr("hermes_ultra.agent_reach.subprocess.run", fake_run)
    adapter = AgentReachAdapter(env={"PATH": "/bin"})

    with pytest.raises(AgentReachError):
        adapter.install_all()


def test_configure_rejects_option_injection():
    adapter = AgentReachAdapter()
    with pytest.raises(ValueError):
        adapter.configure("--system")


def test_upstream_rejects_option_injection():
    adapter = AgentReachAdapter()
    with pytest.raises(ValueError):
        adapter.upstream("--help")
