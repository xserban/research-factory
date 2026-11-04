"""The ml-benchmark domain pack, version 1 (pure data).

Invariants: ``flops`` and ``macs`` are separate COUNT fields; ``value`` and
``variance_value`` are SCORE fields whose units are compared, never converted.
"""

from __future__ import annotations

from factory.packs.model import Check, FieldDef, FieldKind, Pack, UnitFamily

_COUNT_UNITS = ("K", "M", "G", "T", "B", "")
_SCORE_UNITS = ("%", "fraction", "")
_T, _N, _I, _B = FieldKind.TEXT, FieldKind.NUMBER, FieldKind.INTEGER, FieldKind.BOOL
_NONE_U = UnitFamily.NONE


def _f(
    name: str,
    group: str,
    kind: FieldKind,
    family: UnitFamily,
    check: Check,
    units: tuple[str, ...] = (),
    normaliser: str | None = None,
) -> FieldDef:
    return FieldDef(name, group, kind, family, check, units, normaliser)


# Citation markers. Known accepted false positives (safe direction: a spurious
# marker only hides a number from being read as a result): ``[0, 1]``,
# ``[2021]``, ``(June 2021)``.
_UP = "A-Z\u00c0-\u00d6\u00d8-\u00de\u0100-\u017f\u0180-\u024f"
_SURNAME = (
    r"(?:(?:van|von|de|der|den|di|da|del|du|la|le|ter)\s+)*"
    rf"[{_UP}](?:[^\W\d_]|['\u2019-])*"
)
_AUTHORS = rf"{_SURNAME}(?:(?:,\s*(?:(?:and|&)\s+)?|\s+(?:and|&)\s+){_SURNAME}){{0,4}}"
_ENTRY = rf"{_AUTHORS}(?:\s+et al\.?)?,?\s+\d{{4}}[a-z]?"
CITATION_PATTERNS = (
    r"\[\s*\d+(?:\s*[,;\u2013\u2014-]\s*\d+)*\s*\]",
    rf"\({_ENTRY}\)",
    rf"(?<=\(){_ENTRY}(?=;)",
    rf"(?<=;\s){_ENTRY}(?=[;)])",
    rf"\b{_AUTHORS}\s+et al\.?,?\s+(?:\(\d{{4}}[a-z]?\)|\d{{4}}[a-z]?)",
    rf"\b{_AUTHORS},?\s+\(\d{{4}}[a-z]?\)",
    r"\\cite[a-z]*\*?(?:\[[^\]]*\])*\{[^}]*\}",
)

_TQ, _NUM, _NOCHK = Check.TEXT_IN_QUOTE, Check.NUMBER, Check.NONE

ML_BENCHMARK_V1 = Pack(
    name="ml-benchmark",
    version=1,
    fields=(
        _f("method_name", "identity", _T, _NONE_U, _TQ),
        _f("variant", "identity", _T, _NONE_U, _NOCHK),
        _f("is_proposed", "identity", _B, _NONE_U, _NOCHK),
        _f("task", "task", _T, _NONE_U, _NOCHK),
        _f("dataset", "task", _T, _NONE_U, _TQ),
        _f("split", "task", _T, _NONE_U, _NOCHK),
        _f("input_resolution", "task", _T, _NONE_U, _NOCHK, normaliser="resolution"),
        _f("metric", "result", _T, _NONE_U, _TQ),
        _f("value", "result", _N, UnitFamily.SCORE, _NUM, _SCORE_UNITS),
        _f("higher_is_better", "result", _B, _NONE_U, _NOCHK),
        _f("variance_reported", "result", _B, _NONE_U, _NOCHK),
        _f("variance_value", "result", _N, UnitFamily.SCORE, _NUM, _SCORE_UNITS),
        _f("params", "cost", _N, UnitFamily.COUNT, _NUM, _COUNT_UNITS),
        _f("flops", "cost", _N, UnitFamily.COUNT, _NUM, _COUNT_UNITS),
        _f("macs", "cost", _N, UnitFamily.COUNT, _NUM, _COUNT_UNITS),
        _f("throughput", "cost", _N, UnitFamily.OTHER, _NUM),
        _f("latency", "cost", _N, UnitFamily.OTHER, _NUM),
        _f("memory", "cost", _N, UnitFamily.OTHER, _NUM),
        _f("hardware", "cost", _T, _NONE_U, _NOCHK),
        _f("batch_size", "cost", _I, _NONE_U, _NUM),
        _f("precision", "cost", _T, _NONE_U, _NOCHK),
        _f("pretraining_data", "regime", _T, _NONE_U, _NOCHK),
        _f("training_epochs", "regime", _I, _NONE_U, _NUM),
        _f("distillation", "regime", _B, _NONE_U, _NOCHK),
        _f("extra_data", "regime", _B, _NONE_U, _NOCHK),
    ),
    required=("method_name", "task", "dataset", "metric", "value"),
    default_comparability_keys=(
        "task",
        "dataset",
        "split",
        "metric",
        "input_resolution",
        "pretraining_data",
    ),
    citation_patterns=CITATION_PATTERNS,
)
