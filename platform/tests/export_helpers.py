"""Work builders for export tests (no I/O)."""

from datetime import UTC, date, datetime
from typing import Any

from factory.model.work import Dates, Provenance, Work

ULID = "01HZX3Y5K6M7N8P9Q0R1S2T3V4"


def prov() -> Provenance:
    return Provenance(
        source="openalex",
        run_id=f"run_{ULID}",
        query_id=f"qry_{ULID}",
        at=datetime(2026, 1, 1, tzinfo=UTC),
        raw_blob="sha256:" + "a" * 64,
    )


def make_work(**kw: Any) -> Work:
    kw.setdefault("title", "Attention is all you need")
    kw.setdefault("dates", Dates(published=date(2020, 7, 1)))
    return Work.build(provenance=[prov()], **kw)
