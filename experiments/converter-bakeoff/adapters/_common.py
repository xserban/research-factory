"""Helpers shared by the bake-off adapters (experiment code)."""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TOOLS = HERE / "tools"
PANDOC = TOOLS / "pandoc" / "pandoc-3.13-arm64" / "bin" / "pandoc"
JAVA_HOME = TOOLS / "jdk" / "jdk-21.0.13+9" / "Contents" / "Home"
GROBID_DIR = TOOLS / "grobid" / "grobid-0.9.1"
DOCLING_MODELS = TOOLS / "docling-models"

HTML = "text/html"
EPRINT = "application/x-eprint-tar"
PDF = "application/pdf"


def tree_hash(root: Path) -> str:
    """sha256 over the sorted (relative path, file sha256) pairs of every file under `root`."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        file_hash = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                file_hash.update(chunk)
        digest.update(f"{path.relative_to(root).as_posix()}\0{file_hash.hexdigest()}\n".encode())
    return digest.hexdigest()


def unpack_eprint(raw: bytes, dest: Path) -> None:
    """Unpack an arXiv e-print (tar, tar.gz, single gz or a bare .tex) into `dest`.

    Members that would escape `dest`, links and devices are skipped (`filter="data"`).
    """
    import gzip

    data = raw
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    buffer = io.BytesIO(data)
    if tarfile.is_tarfile(buffer):
        buffer.seek(0)
        with tarfile.open(fileobj=buffer) as archive:
            archive.extractall(dest, filter="data")
    else:
        (dest / "main.tex").write_bytes(data)


def find_main_tex(root: Path) -> Path | None:
    """The .tex with `\\documentclass` (and `\\begin{document}` preferred), shallowest first."""
    candidates: list[tuple[int, int, str, Path]] = []
    for path in root.rglob("*.tex"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "\\documentclass" in text:
            has_body = 0 if "\\begin{document}" in text else 1
            candidates.append((has_body, len(path.relative_to(root).parts), path.as_posix(), path))
    return min(candidates)[3] if candidates else None
