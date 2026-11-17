"""Parser v3: a leading author-year citation label (LaTeXML natbib output) is not the authors."""

import pytest

from factory.references.parse import _strip_author_year_label, parse_entry_fields


@pytest.mark.parametrize(
    ("text", "author", "title"),
    [
        (
            "Alabdulmohsin and Steiner (2025) I. Alabdulmohsin and A. P. Steiner A tale of two "
            "structures: do LLMs capture the fractal complexity of language?. In International "
            "Conference on Machine Learning (ICML), Note: Poster External Links: Link",
            "Alabdulmohsin",
            "A tale of two structures: do LLMs capture the fractal complexity of language?",
        ),
        (
            "Baek et al. (2025) J. Baek, S. K. Jauhar, S. Cucerzan, and S. J. Hwang ResearchAgent: "
            "iterative research idea generation over scientific literature with large language "
            "models. In Proceedings of the 2025 Conference of the Nations of the Americas Chapter",
            "Baek",
            "ResearchAgent: iterative research idea generation over scientific literature with "
            "large language models",
        ),
        (
            "Akinwande and Kolter (2024) V. Akinwande and J. Z. Kolter. Acceleratedlingam: "
            "Learning causal dags at the speed of gpus. arXiv preprint",
            "Akinwande",
            "Acceleratedlingam: Learning causal dags at the speed of gpus",
        ),
    ],
)
def test_author_year_label_is_stripped(text: str, author: str, title: str) -> None:
    fields = parse_entry_fields(text)
    assert fields.first_author == author
    assert fields.title == title


def test_organisation_label_is_stripped() -> None:
    assert _strip_author_year_label("OpenAI (2023a) OpenAI. GPT-4 technical report.") == (
        "OpenAI. GPT-4 technical report."
    )


def test_apa_style_year_is_not_a_label() -> None:
    """`Surname, A. (2020). Title.` keeps its authors: the year is followed by a period."""
    fields = parse_entry_fields("Smith, J. (2020). A study of things. Journal of Stuff, 3, 1-2.")
    assert fields.first_author == "Smith"
    assert fields.title == "A study of things"


def test_label_whose_surname_does_not_recur_is_kept() -> None:
    """Only a label whose first surname recurs right after it is read as a label."""
    text = "Deep learning (2015) review of methods. Nature, 521."
    assert _strip_author_year_label(text) == text


@pytest.mark.parametrize(
    ("text", "title"),
    [
        (
            "Junlin Wang, Jue WANG, Ben Athiwaratkun, Ce Zhang, and James Zou. 2025. "
            "Mixture-of-agents enhances large language model capabilities. In ICLR.",
            "Mixture-of-agents enhances large language model capabilities",
        ),
        (
            "Alireza Ghafarollahi and Markus J Buehler. 2025. Sciagents: automating scientific "
            "discovery through bioinspired multi-agent intelligent graph reasoning. Advanced "
            "Materials, 37(22).",
            "Sciagents: automating scientific discovery through bioinspired multi-agent "
            "intelligent graph reasoning",
        ),
        (
            "Cottier et al. [2024] Ben Cottier, Robi Rahman, Loredana Fattorini, Nestor Maslej, "
            "and David Owen. The rising costs of training frontier AI models. arXiv preprint.",
            "The rising costs of training frontier AI models",
        ),
    ],
)
def test_year_after_authors_starts_the_title(text: str, title: str) -> None:
    """A fallback, only when the title would otherwise be a fragment: the title follows a year
    that closes the author list (`Names. 2025. Title.`, `(2025) Title`, `[2024] Names. Title`)."""
    assert parse_entry_fields(text).title == title


@pytest.mark.parametrize(
    "text",
    [
        "OpenAI (2025) OpenAI GPT-5. External Links: Link Cited by: §4.1.",
        "DeepSeek (2025) Deepseek-v3.1-terminus. Accessed 20 Nov 2025.",
        "OpenAI (2025) OpenAI Openai-gpt-rosalind. Note: Cited by: §1.",
    ],
)
def test_fallback_never_takes_a_trailing_note_as_title(text: str) -> None:
    title = parse_entry_fields(text).title or ""
    assert not title.startswith(("Note", "External Links", "Accessed", "Cited by"))
