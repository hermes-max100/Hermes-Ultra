#!/usr/bin/env python3
"""Fail-closed OS containment for Hermes candidate execution.

Candidate commands run in a dedicated child that irreversibly applies:
- Linux Landlock filesystem allowlisting (unprivileged LSM sandbox),
- PR_SET_NO_NEW_PRIVS,
- libseccomp syscall denial for network and high-risk kernel interfaces,
- bounded process/file/core resource limits,
- a minimal environment with an isolated HOME/TMPDIR.

No namespace privilege, sudo, Docker socket, or host-home mount is required.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import glob
import os
import re
import resource
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
MAX_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_OPEN_FILES = 256
MAX_PROCESSES = 128

PR_SET_NO_NEW_PRIVS = 38
LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_RULE_PATH_BENEATH = 1

LL_EXECUTE = 1 << 0
LL_WRITE_FILE = 1 << 1
LL_READ_FILE = 1 << 2
LL_READ_DIR = 1 << 3
LL_REMOVE_DIR = 1 << 4
LL_REMOVE_FILE = 1 << 5
LL_MAKE_CHAR = 1 << 6
LL_MAKE_DIR = 1 << 7
LL_MAKE_REG = 1 << 8
LL_MAKE_SOCK = 1 << 9
LL_MAKE_FIFO = 1 << 10
LL_MAKE_BLOCK = 1 << 11
LL_MAKE_SYM = 1 << 12
LL_REFER = 1 << 13
LL_TRUNCATE = 1 << 14
LL_IOCTL_DEV = 1 << 15
LL_RESOLVE_UNIX = 1 << 16

READ_ACCESS = LL_EXECUTE | LL_READ_FILE | LL_READ_DIR
BASE_WRITE_ACCESS = (
    LL_WRITE_FILE
    | LL_REMOVE_DIR
    | LL_REMOVE_FILE
    | LL_MAKE_DIR
    | LL_MAKE_REG
    | LL_MAKE_FIFO
    | LL_MAKE_SYM
)
FILE_ACCESS_MASK = LL_EXECUTE | LL_WRITE_FILE | LL_READ_FILE | LL_TRUNCATE | LL_IOCTL_DEV | LL_RESOLVE_UNIX

SCMP_ACT_ALLOW = 0x7FFF0000
SCMP_ACT_ERRNO_EPERM = 0x00050000 | errno.EPERM
DENIED_SYSCALLS = (
    # Network and IPC endpoints. Pipes remain available for normal subprocesses.
    "socket", "socketpair", "connect", "bind", "listen", "accept", "accept4",
    "sendto", "recvfrom", "sendmsg", "recvmsg", "sendmmsg", "recvmmsg",
    "shutdown", "getsockname", "getpeername", "setsockopt", "getsockopt", "socketcall",
    # Kernel/namespace attack surface not required by candidate regression tests.
    "ptrace", "process_vm_readv", "process_vm_writev", "bpf", "perf_event_open",
    "userfaultfd", "open_by_handle_at", "mount", "umount2", "pivot_root",
    "setns", "unshare", "kexec_load", "kexec_file_load", "init_module",
    "finit_module", "delete_module", "reboot", "keyctl", "add_key", "request_key",
)


class SandboxIsolationError(RuntimeError):
    pass


class LandlockRulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class LandlockPathBeneathAttr(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def trusted_seccomp_library() -> Path:
    candidates: list[Path] = []
    for pattern in (
        "/lib/*/libseccomp.so.2", "/usr/lib/*/libseccomp.so.2",
        "/lib/libseccomp.so.2", "/usr/lib/libseccomp.so.2",
    ):
        candidates.extend(Path(item) for item in glob.glob(pattern))
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            info = resolved.stat()
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not (stat.S_IMODE(info.st_mode) & 0o022):
            return resolved
    raise SandboxIsolationError("trusted libseccomp.so.2 missing or unsafe")


def _syscall_number(name: str, fallback: int) -> int:
    patterns = (
        "/usr/include/*/asm/unistd_64.h",
        "/usr/include/*/asm/unistd.h",
        "/usr/include/asm-generic/unistd.h",
    )
    regex = re.compile(rf"^#\s*define\s+__NR_{re.escape(name)}\s+(\d+)\s*$")
    for pattern in patterns:
        for filename in glob.glob(pattern):
            try:
                for line in Path(filename).read_text(encoding="utf-8", errors="ignore").splitlines():
                    match = regex.match(line)
                    if match:
                        return int(match.group(1))
            except OSError:
                continue
    return fallback


def landlock_syscalls() -> tuple[int, int, int]:
    return (
        _syscall_number("landlock_create_ruleset", 444),
        _syscall_number("landlock_add_rule", 445),
        _syscall_number("landlock_restrict_self", 446),
    )


def supported_fs_access(abi: int) -> int:
    access = (
        LL_EXECUTE | LL_WRITE_FILE | LL_READ_FILE | LL_READ_DIR | LL_REMOVE_DIR |
        LL_REMOVE_FILE | LL_MAKE_CHAR | LL_MAKE_DIR | LL_MAKE_REG | LL_MAKE_SOCK |
        LL_MAKE_FIFO | LL_MAKE_BLOCK | LL_MAKE_SYM
    )
    if abi >= 2:
        access |= LL_REFER
    if abi >= 3:
        access |= LL_TRUNCATE
    if abi >= 5:
        access |= LL_IOCTL_DEV
    if abi >= 9:
        access |= LL_RESOLVE_UNIX
    return access


def writable_access(abi: int) -> int:
    access = READ_ACCESS | BASE_WRITE_ACCESS
    if abi >= 2:
        access |= LL_REFER
    if abi >= 3:
        access |= LL_TRUNCATE
    return access


def _landlock_add_path(libc: Any, add_nr: int, ruleset_fd: int, path: Path, access: int) -> None:
    if not path.exists():
        return
    try:
        info = path.stat()
    except OSError as exc:
        raise SandboxIsolationError(f"could not stat Landlock path {path}: {exc}") from exc
    allowed_access = access if stat.S_ISDIR(info.st_mode) else access & FILE_ACCESS_MASK
    if allowed_access == 0:
        return
    parent_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    try:
        attr = LandlockPathBeneathAttr(allowed_access=allowed_access, parent_fd=parent_fd)
        rc = libc.syscall(add_nr, ruleset_fd, LANDLOCK_RULE_PATH_BENEATH, ctypes.byref(attr), 0)
        if rc != 0:
            err = ctypes.get_errno()
            raise SandboxIsolationError(f"landlock_add_rule failed for {path}: errno={err}")
    finally:
        os.close(parent_fd)


def apply_landlock(worktree: Path, home: Path) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    create_nr, add_nr, restrict_nr = landlock_syscalls()
    libc.syscall.restype = ctypes.c_long

    abi = int(libc.syscall(create_nr, 0, 0, LANDLOCK_CREATE_RULESET_VERSION))
    if abi < 1:
        err = ctypes.get_errno()
        raise SandboxIsolationError(f"Landlock unavailable or disabled: errno={err}")

    handled = supported_fs_access(abi)
    ruleset_attr = LandlockRulesetAttr(handled_access_fs=handled)
    ruleset_fd = int(libc.syscall(create_nr, ctypes.byref(ruleset_attr), ctypes.sizeof(ruleset_attr), 0))
    if ruleset_fd < 0:
        err = ctypes.get_errno()
        raise SandboxIsolationError(f"landlock_create_ruleset failed: errno={err}")

    try:
        for path in (Path("/usr"), Path("/bin"), Path("/sbin"), Path("/lib"), Path("/lib64")):
            _landlock_add_path(libc, add_nr, ruleset_fd, path, READ_ACCESS)
        for path in (
            Path("/etc/ld.so.cache"), Path("/etc/localtime"), Path("/etc/passwd"),
            Path("/etc/group"), Path("/etc/nsswitch.conf"), Path("/etc/locale.alias"),
            Path("/dev/urandom"),
        ):
            _landlock_add_path(libc, add_nr, ruleset_fd, path, LL_READ_FILE)
        _landlock_add_path(libc, add_nr, ruleset_fd, Path("/dev/null"), LL_READ_FILE | LL_WRITE_FILE)

        rw_access = writable_access(abi)
        _landlock_add_path(libc, add_nr, ruleset_fd, worktree, rw_access)
        _landlock_add_path(libc, add_nr, ruleset_fd, home, rw_access)

        if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            err = ctypes.get_errno()
            raise SandboxIsolationError(f"PR_SET_NO_NEW_PRIVS failed: errno={err}")
        if libc.syscall(restrict_nr, ruleset_fd, 0) != 0:
            err = ctypes.get_errno()
            raise SandboxIsolationError(f"landlock_restrict_self failed: errno={err}")
    finally:
        os.close(ruleset_fd)
    return abi


def apply_seccomp() -> None:
    lib = ctypes.CDLL(str(trusted_seccomp_library()))
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.restype = ctypes.c_int

    ctx = lib.seccomp_init(SCMP_ACT_ALLOW)
    if not ctx:
        raise SandboxIsolationError("seccomp_init failed")
    try:
        added = 0
        for name in DENIED_SYSCALLS:
            number = lib.seccomp_syscall_resolve_name(name.encode("ascii"))
            if number < 0:
                continue
            rc = lib.seccomp_rule_add(ctx, SCMP_ACT_ERRNO_EPERM, number, 0)
            if rc != 0:
                raise SandboxIsolationError(f"seccomp rule failed for {name}: {rc}")
            added += 1
        if added == 0:
            raise SandboxIsolationError("no seccomp deny syscalls resolved")
        if lib.seccomp_load(ctx) != 0:
            raise SandboxIsolationError("seccomp_load failed")
    finally:
        lib.seccomp_release(ctx)


def apply_resource_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (MAX_OPEN_FILES, MAX_OPEN_FILES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_BYTES, MAX_FILE_BYTES))
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (MAX_PROCESSES, MAX_PROCESSES))
    except (ValueError, OSError):
        pass
    try:
        resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))
    except (ValueError, OSError):
        pass


def child_exec(worktree: Path, home: Path, command: str) -> int:
    worktree = worktree.resolve(strict=True)
    home = home.resolve(strict=True)
    tmpdir = home / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chdir(worktree)
    apply_resource_limits()
    abi = apply_landlock(worktree, home)
    apply_seccomp()
    env = {
        "HOME": str(home),
        "TMPDIR": str(tmpdir),
        "PATH": SAFE_PATH,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
        "HERMES_SANDBOX": "1",
        "HERMES_LANDLOCK_ABI": str(abi),
        "NO_NETWORK": "1",
    }
    os.execve("/bin/bash", ["bash", "--noprofile", "--norc", "-c", command], env)
    return 126


def run_isolated(command: str, worktree: Path, home: Path, timeout: int) -> dict[str, Any]:
    started = utc_now()
    helper = Path(__file__).resolve()
    cmd = [
        sys.executable,
        str(helper),
        "--child",
        "--worktree", str(worktree.resolve()),
        "--home", str(home.resolve()),
        "--command", command,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=worktree,
            env={"PATH": SAFE_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb"},
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "cmd": ["sandbox:landlock+seccomp", "bash", "--noprofile", "--norc", "-c", command],
            "cwd": str(worktree),
            "started_at": started,
            "finished_at": utc_now(),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "timed_out": False,
            "isolation": "landlock+seccomp-deny-network",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": ["sandbox:landlock+seccomp", "bash", "--noprofile", "--norc", "-c", command],
            "cwd": str(worktree),
            "started_at": started,
            "finished_at": utc_now(),
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or f"command timed out after {timeout}s",
            "timed_out": True,
            "isolation": "landlock+seccomp-deny-network",
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--worktree")
    parser.add_argument("--home")
    parser.add_argument("--command")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.child or not args.worktree or not args.home or args.command is None:
        print("sandbox-isolation.py is an internal child launcher", file=sys.stderr)
        return 2
    try:
        return child_exec(Path(args.worktree), Path(args.home), args.command)
    except (SandboxIsolationError, OSError, ValueError) as exc:
        print(f"OS sandbox unavailable: {exc}", file=sys.stderr)
        return 126


if __name__ == "__main__":
    raise SystemExit(main())
