# Hermes-Ultra

## Agent-Reach integration

Hermes Ultra treats Agent Reach as a first-class internet-intelligence provider with every currently documented optional channel eligible:

- OpenCLI
- Twitter/X
- XiaoYuZhou
- Xueqiu
- Xiaohongshu
- Reddit
- Facebook
- Instagram
- Bilibili
- LinkedIn

Zero-config Agent-Reach capabilities such as web reading, YouTube, RSS, GitHub, semantic web search, V2EX, and basic Bilibili remain available through the upstream installation as well.

### Install / inspect

Install Agent Reach outside the Hermes workspace, following its upstream directory model:

```bash
pipx install https://github.com/Panniantong/agent-reach/archive/main.zip
agent-reach install --env=auto --channels=all --dry-run
```

After host-level changes are authorized on the target machine:

```bash
agent-reach install --env=auto --system --channels=all
agent-reach doctor
```

Hermes does not copy authentication secrets into this repository. Platform authentication remains in Agent Reach/upstream local configuration and process environment according to the upstream tool's documented flow.

### Python integration

```python
from hermes_ultra import AgentReachAdapter

reach = AgentReachAdapter()

# Read-only discovery of everything Agent Reach can enable.
reach.install_all(dry_run=True)

# Evidence-oriented health snapshot.
print(reach.status_json())

# Once host changes are explicitly authorized:
reach.install_all(system=True)
```

`AgentReachAdapter.upstream()` deliberately does not impose a channel allowlist. This lets Hermes invoke installed Agent-Reach-managed upstream CLIs while retaining one normalized result/error boundary.

### Design rules

1. All Agent-Reach channels are eligible; Hermes does not arbitrarily narrow the provider.
2. Agent Reach remains responsible for backend selection, installation, diagnostics, and its upstream-tool routing model.
3. `agent-reach doctor` output is retained as health evidence instead of being converted into an optimistic success signal.
4. Secrets are never committed to Hermes-Ultra.
5. Host/system installation is a separate operation from read-only inspection.

### Tests

```bash
python -m pip install -e '.[test]'
pytest -q
```

CI is defined in `.github/workflows/test.yml`.
