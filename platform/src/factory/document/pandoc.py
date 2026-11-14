"""pandoc converter: HTML (`-f html`), PubMed Central JATS XML (`-f jats`) and arXiv LaTeX e-prints
(`-f latex`) to GFM Markdown.

pandoc is GPL: it is run only as a subprocess, never linked or bundled. The binary is taken from
the `FACTORY_PANDOC` environment variable, else `PATH`. The LaTeX e-print converter of decision
49, listed in `default_converters` after latexml-html, which keeps HTML. JATS
(`application/jats+xml`, decision 124, proposed) is read from stdin like HTML; pandoc renders
sections, tables and xrefs but not the `<ref-list>` entries (the References heading is kept, its
body is empty); `factory.document.jats_refs` fills it with one paragraph per `<ref>`.

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
from factory.document.errors import ConversionToolError
from factory.document.jats_refs import with_reference_list

HTML = "text/html"
JATS = "application/jats+xml"
EPRINT_TAR = "application/x-eprint-tar"
EPRINT_SINGLE = "application/x-eprint"
PANDOC_ENV = "FACTORY_PANDOC"
TIMEOUT_SECONDS: float = 300
MIN_VERSION = (2, 15)  # `--sandbox` exists from pandoc 2.15
CONVERTER_VERSION = "1.1"


def pandoc_path() -> str | None:
    """The pandoc executable: `FACTORY_PANDOC` if set and present, else the one on PATH."""
    configured = os.environ.get(PANDOC_ENV)
    if configured:
        return configured if Path(configured).is_file() else None
    return shutil.which("pandoc")


def _parse_version(text: str) -> tuple[int, ...]:
    """The leading numeric components of a version string; `()` when there are none."""
    parts: list[int] = []
    for piece in text.split("."):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts)


class PandocConverter:
    """pandoc as a subprocess. `version` raises `ConverterUnavailable` when it is absent."""

    name = "pandoc"
    accepts = frozenset({HTML, JATS, EPRINT_TAR, EPRINT_SINGLE})

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
        if _parse_version(first[-1]) < MIN_VERSION:
            raise ConverterUnavailable("pandoc is older than 2.15 (no --sandbox)")
        return f"{CONVERTER_VERSION}+pandoc {first[-1]}"

    def to_markdown(self, raw: bytes, media_type: str) -> tuple[str, tuple[str, ...]]:
        self.version()
        path = pandoc_path()
        assert path is not None
        base = [path, "--sandbox", "-t", "gfm", "--wrap=none"]
        skipped = 0
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            # Minimal environment: no inherited secrets or config; HOME is the private temp dir.
            env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": tmp}
            try:
                if media_type in (HTML, JATS):
                    proc = subprocess.run(
                        [*base, "-f", "html" if media_type == HTML else "jats"],
                        input=raw,
                        capture_output=True,
                        timeout=TIMEOUT_SECONDS,
                        cwd=work,
                        env=env,
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
                    # `./` keeps the name positional; member names never start with `-` anyway.
                    proc = subprocess.run(
                        [*base, "-f", "latex", f"./{main}"],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        timeout=TIMEOUT_SECONDS,
                        cwd=work,
                        env=env,
                        check=False,
                    )
            except subprocess.TimeoutExpired as exc:
                raise ConversionToolError("pandoc timed out") from exc
            except OSError as exc:
                raise ConversionToolError("pandoc could not be run") from exc
        if proc.returncode != 0:
            raise ConversionToolError(f"pandoc exited with status {proc.returncode}")
        warnings: list[str] = []
        stderr_lines = len(proc.stderr.decode("utf-8", "replace").splitlines())
        if stderr_lines:
            warnings.append(f"pandoc stderr lines: {stderr_lines}")
        if skipped:
            warnings.append(f"e-print members skipped: {skipped}")
        try:
            markdown = proc.stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ConversionToolError("pandoc output is not valid UTF-8") from exc
        if media_type == JATS:
            markdown = with_reference_list(markdown, raw)
        return markdown, tuple(warnings)
