"""Corpus guard and fetch for the converter bake-off (experiment code, outside platform/).

`--check` queries the arXiv API once for every corpus id, fails if a title or abstract matches the
off-topic pattern (decision 47) or if a corpus title differs from the API title. Without `--check`
the script fetches HTML, LaTeX e-print and PDF into the git-ignored `data/raw/<id>/`, but only when
`corpus.toml` carries `approved = "<name> <date>"`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from xml.etree import ElementTree

from factory.config import Settings
from factory.model.work import Identifiers, Work
from factory.sources.fulltext.arxiv import (
    ArxivHtmlRoute,
    ArxivSourceRoute,
    arxiv_version_lookup,
)
from factory.sources.http import PoliteClient, default_http

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus.toml"
RAW = HERE / "data" / "raw"
API = "https://export.arxiv.org/api/query"
PDF_URL = "https://arxiv.org/pdf/{versioned}"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
OFF_TOPIC = re.compile(
    r"(linear|efficient|sub-?quadratic|kernel(ized)?)\s+attention"
    r"|vision transformer|\bViT\b|token (pruning|merging)",
    re.IGNORECASE,
)
TAGS = {"dense-tables", "heavy-math", "two-column-pdf", "custom-macros", "appendix"}


def load_corpus() -> dict:
    with CORPUS.open("rb") as handle:
        return tomllib.load(handle)


def norm_title(title: str) -> str:
    """Case-, whitespace- and punctuation-insensitive form used to compare titles."""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def make_http() -> PoliteClient:
    return default_http(Settings.load(root=HERE))


def api_entries(http: PoliteClient, ids: list[str]) -> dict[str, tuple[str, str]]:
    """{bare id: (title, abstract)} from one batched export-API request."""
    response = http.get(API, {"id_list": ",".join(ids), "max_results": len(ids)})
    out: dict[str, tuple[str, str]] = {}
    for entry in ElementTree.fromstring(response.content).findall("a:entry", ATOM):
        raw_id = (entry.findtext("a:id", "", ATOM)).rsplit("/abs/", 1)[-1]
        title = " ".join(entry.findtext("a:title", "", ATOM).split())
        summary = " ".join(entry.findtext("a:summary", "", ATOM).split())
        out[re.sub(r"v\d+$", "", raw_id)] = (title, summary)
    return out


def check(corpus: dict) -> int:
    papers = corpus["paper"]
    ids = [p["id"] for p in papers]
    problems: list[str] = []
    if len(set(ids)) != len(ids):
        problems.append("duplicate ids")
    for paper in papers:
        unknown = set(paper["tags"]) - TAGS
        if unknown:
            problems.append(f"{paper['id']}: unknown tags {sorted(unknown)}")
    entries = api_entries(make_http(), ids)
    for paper in papers:
        pid = paper["id"]
        if pid not in entries:
            problems.append(f"{pid}: not returned by the arXiv API")
            print(f"{pid}\t<missing>\tFAIL")
            continue
        title, abstract = entries[pid]
        verdicts = []
        if OFF_TOPIC.search(title) or OFF_TOPIC.search(abstract):
            verdicts.append("off-topic")
            problems.append(f"{pid}: off-topic match")
        if norm_title(title) != norm_title(paper["title"]):
            verdicts.append("title-mismatch")
            problems.append(f"{pid}: corpus title differs from API title")
        print(f"{pid}\t{title}\t{'FAIL ' + ','.join(verdicts) if verdicts else 'ok'}")
    for problem in problems:
        print("PROBLEM:", problem, file=sys.stderr)
    print(f"{len(papers)} papers, {len(problems)} problems")
    return 1 if problems else 0


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_one(http: PoliteClient, pid: str) -> dict:
    """Fetch the three raw forms of one paper; record what was and was not retrieved."""
    work = Work.model_construct(identifiers=Identifiers(arxiv=pid))  # routes read only the id
    lookup = arxiv_version_lookup(http)
    answer = lookup.get(pid)
    meta: dict = {"id": pid, "version": answer.versioned, "files": {}}
    if answer.versioned is None:
        meta["error"] = f"no version (api status {answer.status})"
        return meta
    out = RAW / pid
    out.mkdir(parents=True, exist_ok=True)
    versioned = answer.versioned
    results = {
        "html": ArxivHtmlRoute(http, lookup).fetch(work, version=versioned),
        "eprint": ArxivSourceRoute(http, lookup).fetch(work, version=versioned),
    }
    for name, result in results.items():
        info: dict = {"outcome": str(result.outcome), "url": result.url, "reason": result.reason}
        if result.content is not None:
            (out / name).write_bytes(result.content)
            info.update(sha256=sha256(result.content), bytes=len(result.content))
            info["media_type"] = result.media_type
        meta["files"][name] = info
    url = PDF_URL.format(versioned=versioned)
    response = http.fetch(url)
    pdf_info: dict = {"url": url, "http_status": response.status_code}
    if response.status_code == 200 and response.content.startswith(b"%PDF"):
        (out / "pdf").write_bytes(response.content)
        pdf_info.update(outcome="retrieved", sha256=sha256(response.content))
        pdf_info["bytes"] = len(response.content)
    else:
        pdf_info.update(outcome="not-retrieved", reason="no-pdf")
    meta["files"]["pdf"] = pdf_info
    (out / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    return meta


def fetch(corpus: dict) -> int:
    approved = corpus.get("approved")
    if not approved or not str(approved).strip():
        print('refusing to fetch: corpus.toml has no approved = "<name> <date>"', file=sys.stderr)
        return 2
    if check(corpus) != 0:
        print("refusing to fetch: the guard failed", file=sys.stderr)
        return 1
    http = make_http()
    failures = 0
    for paper in corpus["paper"]:
        pid = paper["id"]
        if (RAW / pid / "meta.json").exists():
            print(f"{pid}\tskip (already fetched)")
            continue
        meta = fetch_one(http, pid)
        states = {k: v.get("outcome") for k, v in meta["files"].items()}
        missing = [k for k in ("html", "eprint", "pdf") if states.get(k) != "retrieved"]
        failures += bool(missing) or "error" in meta
        print(f"{pid}\t{meta.get('version')}\t{states}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="run the off-topic/title guard only")
    args = parser.parse_args()
    corpus = load_corpus()
    return check(corpus) if args.check else fetch(corpus)


if __name__ == "__main__":
    sys.exit(main())
