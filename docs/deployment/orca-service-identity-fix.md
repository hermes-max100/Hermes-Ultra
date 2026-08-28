# Orca service identity boundary

Hermes must invoke Orca through the packaged Node-mode CLI against a Hermes-owned paired runtime environment. Hermes must not read the Orca server profile under `/home/orca`, relax `ProtectHome`, or execute the AppImage `AppRun` entrypoint as its CLI.

Production invariants:

- Orca server remains owned by the dedicated `orca` service identity.
- Hermes retains `ProtectHome=true`.
- Hermes CLI path is `/opt/orca/bin/orca-ide`.
- Hermes Orca client state is `/var/lib/hermes/.config/hermes/orca-client/orca` and is owner-only.
- The saved environment is named `hermes-runtime`.
- Pairing credentials are consumed locally, never printed by the bootstrap, and persisted only through Orca's secure environment store.
- Orca completion remains candidate evidence only; Hermes verification and promotion authority are unchanged.
