import hashlib
from pathlib import Path

import pytest

from factory.errors import FactoryError
from factory.events.blobs import BlobIntegrityError, BlobNotFoundError, BlobStore

MISSING_REF = "sha256:" + "0" * 64


def test_put_returns_sha256_ref_and_uses_two_level_layout(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")
    ref = store.put(b"hello")
    digest = hashlib.sha256(b"hello").hexdigest()
    assert ref == f"sha256:{digest}"
    assert store.path(ref) == tmp_path / "blobs" / "sha256" / digest[:2] / digest[2:]
    assert store.get(ref) == b"hello"


def test_put_is_idempotent_and_leaves_no_temp_files(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")
    assert store.put(b"x") == store.put(b"x")
    assert len([p for p in (tmp_path / "blobs").rglob("*") if p.is_file()]) == 1


def test_put_json_is_key_order_independent(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")
    assert store.put_json({"b": 1, "a": [1, "é"]}) == store.put_json({"a": [1, "é"], "b": 1})
    assert store.get_json(store.put_json({"a": 1})) == {"a": 1}


def test_tampered_blob_raises(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")
    ref = store.put(b"original")
    store.path(ref).write_bytes(b"changed")
    with pytest.raises(BlobIntegrityError):
        store.get(ref)


def test_missing_blob_raises_not_found(tmp_path: Path) -> None:
    store = BlobStore(tmp_path / "blobs")
    with pytest.raises(BlobNotFoundError):
        store.get(MISSING_REF)
    assert not store.exists(MISSING_REF)


def test_blob_errors_are_factory_errors() -> None:
    assert issubclass(BlobNotFoundError, FactoryError)
    assert issubclass(BlobIntegrityError, FactoryError)


@pytest.mark.parametrize("bad_ref", ["md5:abc", "sha256:ABC", "sha256:" + "a" * 63, ""])
def test_malformed_refs_are_rejected_everywhere(tmp_path: Path, bad_ref: str) -> None:
    store = BlobStore(tmp_path / "blobs")
    with pytest.raises(ValueError):
        store.path(bad_ref)
    with pytest.raises(ValueError):
        store.get(bad_ref)
    with pytest.raises(ValueError):
        store.get_json(bad_ref)
    with pytest.raises(ValueError):
        store.exists(bad_ref)
