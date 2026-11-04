"""pandoc converter: HTML (`-f html`) and arXiv LaTeX e-prints (`-f latex`) to GFM Markdown.

pandoc is GPL: it is run only as a subprocess, never linked or bundled. The binary is taken from
the `FACTORY_PANDOC` environment variable, else `PATH`. Inactive until decision 49: not in
`default_converters`; see `factory.document.optional`.

E-print archives are unpacked in memory (`factory.document.eprint`, with caps and safe names),
written to a private temporary directory, and the main .tex is converted. Warnings carry counts
only, never document text. Output is deterministic for a fixed pandoc version and input.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from factory.document.converter import ConverterUnavailable
from factory.document.eprint import EprintError, find_main_tex, unpack_eprint

HTML = "text/html"
EPRINT_TAR = "application/x-eprint-tar"
EPRINT_SINGLE = "application/x-eprint"
PANDOC_ENV = "FACTORY_PANDOC"
TIMEOUT_SECONDS = 300
CONVERTER_VERSION = "1.0"


def pandoc_path() -> str | None:
    """The pandoc executable: `FACTORY_PANDOC` if set and present, else the one on PATH."""
    configured = os.environ.get(PANDOC_ENV)
    if configured:
        return configured if Path(configured).is_file() else None
    return shutil.which("pandoc")


class PandocConverter:
    """pandoc as a subprocess. `version` raises `ConverterUnavailable` when it is absent."""

    name = "pandoc"
    accepts = frozenset({HTML, EPRINT_TAR, EPRINT_SINGLE})

    def version(self) -> str:
        path = pandoc_path()
        if path is None:
            raise ConverterUnavailable("pandoc is not installed (set FACTORY_PANDOC or use PATH)")
        try:
            out = subprocess.run(
                [path, "--version"], capture_output=True, text=True, check=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConverterUnavailable("pandoc could not be run") from exc
        first = out.stdout.splitlines()[0].split() if out.stdout else []
        if len(first) < 2:
            raise ConverterUnavailable("pandoc version output is unreadable")
        return f"{CONVERTER_VERSION}+pandoc {first[-1]}"

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        self.version()
        path = pandoc_path()
        assert path is not None
        base = [path, "-t", "gfm", "--wrap=none"]
        skipped = 0
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            if media_type == HTML:
                proc = subprocess.run(
                    [*base, "-f", "html"],
                    input=raw,
                    capture_output=True,
                    timeout=TIMEOUT_SECONDS,
                    cwd=work,
                    check=False,
                )
            else:
                files, skipped = unpack_eprint(raw)
                main = find_main_tex(files)
                if main is None:
                    raise EprintError("no .tex file declares a document class")
                for name, content in files.items():
                    target = work / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                proc = subprocess.run(
                    [*base, "-f", "latex", main],
                    capture_output=True,
                    timeout=TIMEOUT_SECONDS,
                    cwd=work,
                    check=False,
                )
        if proc.returncode != 0:
            raise RuntimeError(f"pandoc exited with status {proc.returncode}")
        warnings: list[str] = []
        stderr_lines = len(proc.stderr.decode("utf-8", "replace").splitlines())
        if stderr_lines:
            warnings.append(f"pandoc stderr lines: {stderr_lines}")
        if skipped:
            warnings.append(f"e-print members skipped: {skipped}")
        return proc.stdout.decode("utf-8"), tuple(warnings)
