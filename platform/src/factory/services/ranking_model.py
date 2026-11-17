"""The embedding model that ranks records for screening (decision 116, slice 8, IDEA-42).

The model ranks; it never judges, includes or excludes. It is SPECTER2's base encoder
(`allenai/specter2_base`, Apache-2.0): the input is `title [SEP] abstract`, the vector is the CLS
token of the last hidden layer, and similarity is the cosine. Like docling (decision 49) it runs
offline from supplied weights and is an optional extra, `ranker` (transformers, torch). The
platform never downloads weights, never calls a remote model and never calls an LLM.

Supplying the weights, once, by the researcher (not run by the platform):

    huggingface-cli download allenai/specter2_base --local-dir ~/models/specter2_base
    # or: python -c "from huggingface_hub import snapshot_download as d; \
    #   d('allenai/specter2_base', local_dir='$HOME/models/specter2_base')"
    export FACTORY_RANKER_MODEL=~/models/specter2_base

The model name, the tree hash of the weights directory (which identifies the revision exactly) and
the library versions are recorded with every ranking. `Embedder` is the interface the ranking
service uses, so the service is testable without torch.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from importlib import metadata
from pathlib import Path
from typing import Any, Protocol

from factory.document.docling import tree_hash
from factory.errors import FactoryValidationError, ValidationIssue

MODEL_ENV = "FACTORY_RANKER_MODEL"
MODEL_ID = "allenai/specter2_base"
MAX_LENGTH = 512
BATCH = 16


class Embedder(Protocol):
    """Turns texts into vectors. Deterministic for fixed weights and inputs.

    `model_id` names the model, `weights_hash` is the tree hash of its weights and `software` names
    the libraries that ran it; all three are recorded with a ranking."""

    @property
    def model_id(self) -> str: ...

    @property
    def weights_hash(self) -> str: ...

    @property
    def software(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def ranker_unavailable(reason: str) -> FactoryValidationError:
    """The refusal for a missing extra or missing weights; it names the remedy."""
    return FactoryValidationError(
        [
            ValidationIssue(
                "ranker",
                f"{reason}; install the extra (`uv sync --extra ranker`) and set {MODEL_ENV} to a "
                f"local directory holding {MODEL_ID} (see factory.services.ranking_model)",
            )
        ]
    )


class Specter2Embedder:
    """SPECTER2 base from a local directory; the libraries are imported on first use."""

    def __init__(self, directory: Path | None = None) -> None:
        configured = os.environ.get(MODEL_ENV)
        path = directory if directory is not None else Path(configured) if configured else None
        if path is None:
            raise ranker_unavailable(f"{MODEL_ENV} is not set")
        if not path.is_dir():
            raise ranker_unavailable(f"{path} is not a directory")
        self._dir = path
        self._weights_hash: str | None = None
        self._loaded: tuple[Any, Any, Any] | None = None

    @property
    def model_id(self) -> str:
        return MODEL_ID

    @property
    def weights_hash(self) -> str:
        if self._weights_hash is None:
            self._weights_hash = tree_hash(self._dir)
        return self._weights_hash

    @property
    def software(self) -> str:
        try:
            return (
                f"transformers=={metadata.version('transformers')} "
                f"torch=={metadata.version('torch')}"
            )
        except metadata.PackageNotFoundError as exc:
            raise ranker_unavailable("transformers or torch is not installed") from exc

    def _load(self) -> tuple[Any, Any, Any]:
        if self._loaded is None:
            try:
                import torch
                from transformers import AutoModel, AutoTokenizer
            except ImportError as exc:
                raise ranker_unavailable("transformers or torch is not installed") from exc
            try:
                tokenizer = AutoTokenizer.from_pretrained(self._dir, local_files_only=True)
                model = AutoModel.from_pretrained(self._dir, local_files_only=True)
            except (OSError, ValueError) as exc:  # newer transformers raise ValueError for no files
                raise ranker_unavailable(f"{self._dir} holds no loadable model") from exc
            model.eval()
            self._loaded = (torch, tokenizer, model)
        return self._loaded

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """CLS vectors, in the order of `texts`. Texts are `title [SEP] abstract` already; they are
        embedded in fixed batches, on the CPU, without gradients."""
        torch, tokenizer, model = self._load()
        out: list[list[float]] = []
        with torch.no_grad():
            for start in range(0, len(texts), BATCH):
                batch = list(texts[start : start + BATCH])
                inputs = tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=MAX_LENGTH,
                    return_tensors="pt",
                )
                hidden = model(**inputs).last_hidden_state[:, 0, :]
                out.extend([float(x) for x in row] for row in hidden.tolist())
        return out
