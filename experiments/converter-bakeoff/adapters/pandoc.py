"""pandoc candidate: HTML (`-f html -t gfm`) and LaTeX e-print (`-f latex -t gfm`)."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from factory.document.converter import ConverterUnavailable

from adapters._common import EPRINT, HTML, PANDOC, find_main_tex, unpack_eprint

TIMEOUT = 300


class PandocConverter:
    """Runs the pinned pandoc binary as a subprocess; GPL, so it is never linked."""

    name = "pandoc"
    accepts = frozenset({HTML, EPRINT})

    def version(self) -> str:
        if not PANDOC.exists():
            raise ConverterUnavailable(f"pandoc binary missing at {PANDOC}")
        out = subprocess.run([str(PANDOC), "--version"], capture_output=True, text=True, check=True)
        return "pandoc " + out.stdout.splitlines()[0].split()[-1]

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        self.version()
        base = [str(PANDOC), "-t", "gfm", "--wrap=none"]
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            if media_type == HTML:
                proc = subprocess.run(
                    [*base, "-f", "html"], input=raw, capture_output=True, timeout=TIMEOUT, cwd=work
                )
            else:
                unpack_eprint(raw, work)
                main = find_main_tex(work)
                if main is None:
                    raise ValueError("no .tex file with \\documentclass in the e-print")
                proc = subprocess.run(
                    [*base, "-f", "latex", str(main.relative_to(work))],
                    capture_output=True,
                    timeout=TIMEOUT,
                    cwd=work,
                )
        if proc.returncode != 0:
            raise RuntimeError(f"pandoc exit {proc.returncode}")
        stderr_lines = len(proc.stderr.decode("utf-8", "replace").splitlines())
        warnings = (f"pandoc stderr lines: {stderr_lines}",) if stderr_lines else ()
        return proc.stdout.decode("utf-8"), warnings
