# August 23 Agent Upgrades

Hermes now treats Agent Plugins 1.0 as the portable external capability intake format. `plugin-intake.py` inspects `plugin.json`, `skills/*/SKILL.md`, and `mcp.json`, fingerprints the package, and hands only valid candidates to the existing Trust Gate. Discovery never installs or activates a plugin.

The dynamic router's Gemini worker lane now targets `gemini-3.7-flash` for high-throughput coding/tool work when Google credentials are available. Explicit model overrides still win; legal/security routing boundaries remain unchanged. Execution success remains subject to Hermes's existing proof/test gates.

`provenance-envelope.py` provides a deterministic data-plane boundary for external observations. Every envelope binds source, origin, timestamp, content hash, and trust class. External observations are `data_only`; an external origin cannot assert `internal_trusted`. Callers may also reject nested authority/configuration claims before context or memory ingestion.
