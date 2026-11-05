"""Can this root host projects? (slice 5 ruling 4; `factory server check`.)

The write lock is `flock`, which needs a local file system, and literature, indexes and credentials
must stay out of git. Each failed condition is one issue; an empty list means the root is fit.
"""

import fcntl
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

from factory.config import Settings
from factory.errors import ValidationIssue

NETWORK_FILESYSTEMS = frozenset({"nfs", "nfs4", "cifs", "smbfs", "fuse.sshfs"})
GITIGNORED = ("library/", ".index/", ".server/")

# The other process of the probe: exit 0 when the lock excludes it, 1 when it was granted.
_PROBE = """
import fcntl, sys
with open(sys.argv[1], "a") as handle:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(0)
    sys.exit(1)
"""
_PROBE_TIMEOUT_SECONDS = 30


def server_check(settings: Settings) -> list[ValidationIssue]:
    return [*_filesystem(settings.root), *_lock(settings.root), *_gitignore(settings.root)]


def linux_filesystem(root: Path, mounts: str) -> str | None:
    """The type of the deepest mount holding `root`, from the text of `/proc/mounts`."""
    best: tuple[int, str] | None = None
    for line in mounts.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        point = Path(fields[1].replace("\\040", " "))
        if root == point or point in root.parents:
            depth = len(point.parts)
            if best is None or depth >= best[0]:
                best = (depth, fields[2])
    return None if best is None else best[1]


def mac_filesystem(root: Path, mounts: str) -> str | None:
    """The type of the deepest mount holding `root`, from the output of `mount` on macOS:
    `<device> on <point> (<type>, <options>)`."""
    best: tuple[int, str] | None = None
    for line in mounts.splitlines():
        head, separator, tail = line.rpartition(" (")
        _, on, mounted = head.partition(" on ")
        if not separator or not on:
            continue
        point = Path(mounted)
        if root == point or point in root.parents:
            depth = len(point.parts)
            if best is None or depth >= best[0]:
                best = (depth, tail.split(",")[0].rstrip(")").strip())
    return None if best is None else best[1]


def _filesystem(root: Path) -> list[ValidationIssue]:
    resolved = root.resolve()
    try:
        if platform.system() == "Darwin":
            listing = subprocess.run(["mount"], capture_output=True, text=True, check=True).stdout
            kind = mac_filesystem(resolved, listing)
        else:
            kind = linux_filesystem(resolved, Path("/proc/mounts").read_text())
    except (OSError, subprocess.CalledProcessError) as exc:
        return [ValidationIssue("root", f"cannot read the mount table: {exc}")]
    if kind is None:
        return [ValidationIssue("root", "no mount found for the factory root")]
    if kind in NETWORK_FILESYSTEMS:
        return [ValidationIssue("root", f"on a network file system ({kind}): flock is unreliable")]
    return []


def _lock(root: Path) -> list[ValidationIssue]:
    """Hold a lock here and ask a second process to take it: the same call `Index` relies on."""
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix=".flock-probe-") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX)
            probe = subprocess.run(
                [sys.executable, "-I", "-c", _PROBE, held.name],
                capture_output=True,
                timeout=_PROBE_TIMEOUT_SECONDS,
                check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        return [ValidationIssue("lock", f"flock probe failed: {exc}")]
    if probe.returncode != 0:
        return [ValidationIssue("lock", "flock does not exclude a second process on this root")]
    return []


def _gitignore(root: Path) -> list[ValidationIssue]:
    path = root / ".gitignore"
    entries = {line.strip() for line in path.read_text().splitlines()} if path.is_file() else set()
    return [
        ValidationIssue("gitignore", f".gitignore does not list {entry}")
        for entry in GITIGNORED
        if entry not in entries
    ]
