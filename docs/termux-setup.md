# Termux Setup

Use Termux as the launcher, but run Hermes Max inside an Ubuntu proot. This is
the most reliable Android path because OBLITERATUS depends on PyTorch, Gradio,
Transformers, and manylinux-style Python wheels that do not install cleanly in
native Termux.

## Requirements

- Android device with Termux installed from F-Droid.
- At least 8 GB free storage for the full Python environment.
- More storage if you later download model weights.
- AArch64/ARM64 device recommended.

## 1. Prepare Termux

```bash
pkg update && pkg upgrade -y
pkg install -y proot-distro tar coreutils curl
termux-setup-storage
```

## 2. Install Ubuntu

```bash
proot-distro install ubuntu
```

## 3. Put The Bundle In Downloads

Copy the archive to Android Downloads:

```text
hermes-max-build-with-logs-YYYYMMDDTHHMMSSZ.tar.gz
```

Then enter Ubuntu with shared storage:

```bash
proot-distro login ubuntu --shared-tmp
```

## 4. Install Ubuntu Dependencies

Inside Ubuntu:

```bash
apt update
apt install -y python3 python3-venv python3-pip git build-essential curl ca-certificates
```

## 5. Extract Hermes Max

Inside Ubuntu, Android Downloads is usually available through the Termux home
bind mount. If this path does not exist, run `ls /data/data/com.termux/files/home`
and locate the archive manually.

```bash
mkdir -p /root/hermes-max
tar -xzf /data/data/com.termux/files/home/storage/downloads/hermes-max-build-with-logs-*.tar.gz -C /root/hermes-max
cd /root/hermes-max
```

If you copied the archive somewhere else, replace the path after `tar -xzf`.

## 6. Restore Python Environment

```bash
bash scripts/restore-hermes-build.sh
```

The restore script checks required dependencies first, writes install logs, and
performs first-run Skill OS configuration once. On ARM64 Ubuntu/proot it pins
`torch==2.5.1` where available, removes incompatible CUDA packages when safe,
and fixes the `fsspec` version for `datasets`.

Install logs:

```bash
.hermes/install/install.log
.hermes/install/system.log
```

First-run state:

```bash
.hermes/state/router.conf
.hermes/state/sweep.conf
.hermes/state/install.env
.hermes/state/first-run-config.done
```

To test dependency/config setup without reinstalling Python packages:

```bash
bash scripts/restore-hermes-build.sh --verify-only --no-system-log-monitor
```

## 7. Verify

```bash
src/system/obliteratus-runner.sh doctor
bash tests/test_direct_mode_policy.sh
bash tests/test_dynamic_router.sh
```

## 8. Run OBLITERATUS UI

```bash
src/system/obliteratus-runner.sh ui-start --port 7860
```

Open from Android:

```text
http://127.0.0.1:7860
```

Stop it:

```bash
src/system/obliteratus-runner.sh ui-stop
```

## Notes

- Do not move `.venv` from another machine. Rebuild it on-device.
- Do not expect CUDA on Android. This is CPU/local runtime unless you attach a
  separate remote GPU workflow.
- Avoid downloading large models until the environment passes `doctor`.
- If storage is tight, use the clean archive instead of the logs-included archive.
