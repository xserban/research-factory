import gzip
import io
import tarfile
from pathlib import Path

from factory.references.bbl import BblEntry, align, read_bbl
from factory.references.parse import parse_bibliography
from tests.references_helpers import manifest

BBL = (Path(__file__).parent / "fixtures" / "references" / "sample.bbl").read_bytes()


def _tar_gz(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_read_plain_bbl() -> None:
    entries = read_bbl(BBL)
    assert [e.key for e in entries] == ["marrow2016", "quill2020"]
    assert entries[0].text == (
        "K. Marrow, S. Vale, and Q. Quill. Layered gradient folding. NEURA, 2016. "
        "doi:10.1234/neura.2016.90."
    )
    assert "arXiv:2010.99999" in entries[1].text


def test_read_bbl_from_tar_gz_and_oversize() -> None:
    archive = _tar_gz({"paper/main.tex": b"\\bibitem{no}", "paper/refs.bbl": BBL, "x.txt": b"hi"})
    assert [e.key for e in read_bbl(archive)] == ["marrow2016", "quill2020"]
    assert read_bbl(archive, max_bytes=100) == []
    bomb = gzip.compress(b"a" * 10_000)
    assert read_bbl(bomb, max_bytes=1000) == []


def test_read_bbl_without_bbl_or_garbage() -> None:
    assert read_bbl(_tar_gz({"main.tex": b"hello"})) == []
    assert read_bbl(b"") == []
    assert read_bbl(b"\x1f\x8bnot really gzip") == []
    assert read_bbl(b"no bibitems here") == []


def test_read_gzipped_plain_bbl() -> None:
    assert len(read_bbl(gzip.compress(BBL))) == 2


def test_bbl_alignment_by_count() -> None:
    bib = parse_bibliography(manifest(["[1] K. Marrow. Layered. 2016.", "[2] A. Q. T."], []))
    aligned = align(bib, read_bbl(BBL))
    assert (aligned.status, aligned.bib_count, aligned.bbl_count) == ("aligned", 2, 2)
    assert aligned.fields[0] is not None and aligned.fields[0].doi == "10.1234/neura.2016.90"
    assert aligned.fields[1] is not None and aligned.fields[1].arxiv == "2010.99999"

    short = parse_bibliography(manifest(["[1] K. Marrow. Layered. 2016."], []))
    mismatch = align(short, read_bbl(BBL))
    assert (mismatch.status, mismatch.bib_count, mismatch.bbl_count) == ("count-mismatch", 1, 2)
    assert mismatch.fields == (None,)


def test_absent_bbl() -> None:
    bib = parse_bibliography(manifest(["[1] K. Marrow. Layered. 2016."], []))
    result = align(bib, [])
    assert (result.status, result.bbl_count, result.fields) == ("absent", 0, (None,))


def test_bibitem_without_label_and_with_nested_braces() -> None:
    text = (
        b"\\bibitem{k1} A.~Name. \\newblock {\\em Title} \\url{http://x.org/a_b}.\n"
        b"\\bibitem[{A[1]}]{k2} B. C.\n"
    )
    assert read_bbl(text) == [
        BblEntry("k1", "A. Name. Title http://x.org/a_b."),
        BblEntry("k2", "B. C."),
    ]


def test_unclosed_href_is_linear_time() -> None:
    import time

    t0 = time.perf_counter()
    read_bbl(b"\\bibitem{k} " + b"\\href{" * 20000)
    read_bbl(b"\\bibitem{k} " + b"\\doi{" * 20000 + b"\\url{" * 20000)
    assert time.perf_counter() - t0 < 0.5


def test_decompressed_tar_over_limit_is_rejected() -> None:
    """The limit bounds the decompressed tar; member sizes can only be smaller than it."""
    archive = _tar_gz({"a.bbl": BBL, "b.bbl": BBL})
    raw = gzip.decompress(archive)
    assert len(raw) > len(BBL) * 2
    assert read_bbl(archive, max_bytes=len(raw) - 1) == []
    assert len(read_bbl(archive, max_bytes=len(raw))) == 4
    assert read_bbl(raw, max_bytes=len(raw) - 1) == []


def test_outer_archive_over_limit_is_rejected() -> None:
    assert read_bbl(BBL, max_bytes=len(BBL) - 1) == []
    assert len(read_bbl(BBL, max_bytes=len(BBL))) == 2


def test_members_are_read_in_name_order() -> None:
    b = b"\\bibitem{kb} Bee. T. 2002.\n"
    a = b"\\bibitem{ka} Ay. T. 2001.\n"
    assert [e.key for e in read_bbl(_tar_gz({"b.bbl": b, "a.bbl": a}))] == ["ka", "kb"]
