import hashlib
import json
import os
import re
from pathlib import Path

from pydantic import JsonValue

from factory.canonical import canonical_json
from factory.errors import FactoryError

BLOB_REF_RE = r"^sha256:[0-9a-f]{64}$"
_BLOB_REF = re.compile(BLOB_REF_RE)
_PREFIX = "sha256:"


class BlobNotFoundError(FactoryError):
    """No blob is stored under the requested ref."""


class BlobIntegrityError(FactoryError):
    """A stored blob no longer hashes to its ref."""


class BlobStore:
    """Content-addressed storage: blobs live at `<root>/sha256/<2>/<62>`."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        target = self._path_for(digest)
        if not target.exists():
            self._atomic_write(target, data)
        return f"{_PREFIX}{digest}"

    def put_json(self, value: JsonValue) -> str:
        return self.put(canonical_json(value))

    def get(self, ref: str) -> bytes:
        path = self.path(ref)
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise BlobNotFoundError(f"no blob for {ref}") from exc
        if f"{_PREFIX}{hashlib.sha256(data).hexdigest()}" != ref:
            raise BlobIntegrityError(f"blob {ref} does not match its content")
        return data

    def get_json(self, ref: str) -> JsonValue:
        value: JsonValue = json.loads(self.get(ref))
        return value

    def exists(self, ref: str) -> bool:
        return self.path(ref).is_file()

    def path(self, ref: str) -> Path:
        if not _BLOB_REF.fullmatch(ref):
            raise ValueError(f"not a blob ref: {ref!r}")
        return self._path_for(ref[len(_PREFIX) :])

    def _path_for(self, digest: str) -> Path:
        return self._root / "sha256" / digest[:2] / digest[2:]

    @staticmethod
    def _atomic_write(target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.tmp-{os.getpid()}")
        try:
            with tmp.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
