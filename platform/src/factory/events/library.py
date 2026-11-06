"""The lab library and a project's view of it (decision 39; slice 5, plan deploy-C).

`LabLibrary` is a `BlobStore` at `<root>/library/`; it is in use once that directory exists.
`ProjectLibrary` is what `Project.library` is: reads and writes as a stage-0 project had them,
extended by the lab store.

Invariants:
- Reads: the project-local store first (stage 0 and not yet consolidated files), then the lab
  library, and the lab library serves a hash only if the project's own events reference it
  (`referenced`) or this view stored it itself. Otherwise the blob is as missing as an unknown one.
- Writes go to the lab library when it is in use, else to the project-local store.
- A blob is always verified against its ref on read; nothing here writes an event.
"""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from pydantic import JsonValue

from factory.canonical import canonical_json
from factory.events.blobs import BlobIntegrityError, BlobNotFoundError, BlobStore

LIBRARY_DIR = "library"


class LabLibrary(BlobStore):
    """One content-addressed store per lab, at `<root>/library`."""

    def __init__(self, root: Path) -> None:
        self.directory = root / LIBRARY_DIR
        super().__init__(self.directory)

    @property
    def in_use(self) -> bool:
        return self.directory.is_dir()

    def put_verified(self, ref: str, data: bytes) -> bool:
        """Store `data` under `ref` only if it hashes to `ref`; False (nothing stored) otherwise."""
        if f"sha256:{hashlib.sha256(data).hexdigest()}" != ref:
            return False
        self.put(data)
        return True


class ProjectLibrary:
    """A project's view of the literature: local files, then the lab library by reference."""

    def __init__(
        self, local: BlobStore, lab: LabLibrary | None, referenced: Callable[[str], bool]
    ) -> None:
        self._local = local
        self._lab = lab
        self._referenced = referenced
        self._stored: set[str] = set()

    def _lab_store(self) -> LabLibrary | None:
        lab = self._lab
        return lab if lab is not None and lab.in_use else None

    def _lab_readable(self, ref: str) -> bool:
        lab = self._lab_store()
        if lab is None:
            return False
        return lab.exists(ref) and (ref in self._stored or self._referenced(ref))

    def put(self, data: bytes) -> str:
        lab = self._lab_store()
        ref = (lab if lab is not None else self._local).put(data)
        if lab is not None:
            self._stored.add(ref)
        return ref

    def put_json(self, value: JsonValue) -> str:
        return self.put(canonical_json(value))

    def get(self, ref: str) -> bytes:
        if self._local.exists(ref):
            try:
                return self._local.get(ref)
            except BlobIntegrityError:
                if not self._lab_readable(ref):
                    raise
        lab = self._lab_store()
        if lab is not None and self._lab_readable(ref):
            return lab.get(ref)
        raise BlobNotFoundError(f"no blob for {ref}")

    def get_json(self, ref: str) -> JsonValue:
        value: JsonValue = json.loads(self.get(ref))
        return value

    def exists(self, ref: str) -> bool:
        return self._local.exists(ref) or self._lab_readable(ref)

    def path(self, ref: str) -> Path:
        """Where `ref` is read from, else where it would be written."""
        if self._local.exists(ref):
            return self._local.path(ref)
        lab = self._lab_store()
        if lab is not None:
            return lab.path(ref)
        return self._local.path(ref)

    @property
    def local(self) -> BlobStore:
        """The project-local store, which consolidation empties."""
        return self._local

    @property
    def lab(self) -> LabLibrary | None:
        return self._lab_store()
