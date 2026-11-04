"""Always-on tests of the in-memory e-print unpacker."""

import gzip
import io
import tarfile

import pytest

from factory.document import eprint
from factory.document.eprint import EprintError, find_main_tex, safe_member_name, unpack_eprint
from factory.errors import FactoryError


def _tar(members: list[tuple[str, bytes]], *, gz: bool = True) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, content in members:
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    data = buffer.getvalue()
    return gzip.compress(data, mtime=0) if gz else data


def test_unpacks_gzip_tar() -> None:
    files, skipped = unpack_eprint(_tar([("a.tex", b"x"), ("sub/b.tex", b"y")]))
    assert files == {"a.tex": b"x", "sub/b.tex": b"y"}
    assert skipped == 0


def test_unpacks_plain_tar_and_single_gzip_and_bare_tex() -> None:
    assert unpack_eprint(_tar([("a.tex", b"x")], gz=False))[0] == {"a.tex": b"x"}
    assert unpack_eprint(gzip.compress(b"\\documentclass{x}", mtime=0))[0] == {
        "main.tex": b"\\documentclass{x}"
    }
    assert unpack_eprint(b"plain")[0] == {"main.tex": b"plain"}


@pytest.mark.parametrize(
    "name", ["../evil.tex", "a/../../evil.tex", "/etc/passwd", "a\\b.tex", "", ".", "a//../.."]
)
def test_unsafe_names_are_rejected(name: str) -> None:
    assert safe_member_name(name) is None


def test_safe_names_are_normalised() -> None:
    assert safe_member_name("./a/./b.tex") == "a/b.tex"


def test_traversal_members_are_skipped_not_extracted() -> None:
    files, skipped = unpack_eprint(_tar([("../evil.tex", b"x"), ("ok.tex", b"y")]))
    assert files == {"ok.tex": b"y"}
    assert skipped == 1


def test_links_are_skipped() -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        link = tarfile.TarInfo("link.tex")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        archive.addfile(link)
    files, skipped = unpack_eprint(buffer.getvalue())
    assert files == {}
    assert skipped == 1


def test_member_count_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eprint, "MAX_MEMBERS", 2)
    with pytest.raises(EprintError, match="too many members"):
        unpack_eprint(_tar([("a", b""), ("b", b""), ("c", b"")]))


def test_file_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eprint, "MAX_FILE_BYTES", 4)
    with pytest.raises(EprintError, match="size cap"):
        unpack_eprint(_tar([("a", b"12345")]))


def test_total_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eprint, "MAX_TOTAL_BYTES", 6)
    with pytest.raises(EprintError, match="total size cap"):
        unpack_eprint(_tar([("a", b"1234"), ("b", b"1234")], gz=False))


def test_gzip_bomb_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eprint, "MAX_TOTAL_BYTES", 100)
    with pytest.raises(EprintError, match="size cap"):
        unpack_eprint(gzip.compress(b"0" * 10_000, mtime=0))


def test_corrupt_inputs_raise() -> None:
    with pytest.raises(EprintError):
        unpack_eprint(b"\x1f\x8bnot gzip")
    with pytest.raises(EprintError):
        unpack_eprint(_tar([("a", b"x")], gz=False)[:700] + b"\x00" * 3 + b"junk")


def test_error_messages_carry_no_member_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eprint, "MAX_FILE_BYTES", 1)
    with pytest.raises(EprintError) as info:
        unpack_eprint(_tar([("secret-name.tex", b"12")]))
    assert "secret" not in str(info.value)


def test_main_tex_prefers_body_then_shallow_then_name() -> None:
    files = {
        "z.tex": b"\\documentclass{a}\\begin{document}x",
        "sub/a.tex": b"\\documentclass{a}\\begin{document}x",
        "pre.tex": b"\\documentclass{a}",
        "inc.tex": b"just text",
        "notes.txt": b"\\documentclass",
    }
    assert find_main_tex(files) == "z.tex"
    del files["z.tex"]
    assert find_main_tex(files) == "sub/a.tex"
    del files["sub/a.tex"]
    assert find_main_tex(files) == "pre.tex"
    assert find_main_tex({"inc.tex": b"text"}) is None


@pytest.mark.parametrize("name", ["--lua-filter=a.tex", "-x.tex", "sub/-y.tex", "a/--b/c.tex"])
def test_names_with_a_leading_dash_component_are_rejected(name: str) -> None:
    assert safe_member_name(name) is None


def test_non_utf8_roundtrip_name_is_rejected() -> None:
    assert safe_member_name("bad\udcff.tex") is None


def test_name_that_is_a_prefix_of_another_is_rejected() -> None:
    with pytest.raises(EprintError, match="conflict"):
        unpack_eprint(_tar([("a", b"x"), ("a/b.tex", b"y")]))
    with pytest.raises(EprintError, match="conflict"):
        unpack_eprint(_tar([("a/b.tex", b"y"), ("a", b"x")]))


def test_total_cap_is_100_mb() -> None:
    assert eprint.MAX_TOTAL_BYTES == 100 * 1024 * 1024


def test_error_is_a_factory_error() -> None:
    assert issubclass(EprintError, FactoryError)


def test_find_main_tex_ignores_commented_documentclass() -> None:
    files = {"a.tex": b"% \\documentclass{x}\n\\input{b}", "b.tex": b"\\documentclass{x}"}
    assert find_main_tex(files) == "b.tex"
    assert find_main_tex({"a.tex": b"  % \\documentclass{x}"}) is None
