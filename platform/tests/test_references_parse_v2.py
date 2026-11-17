"""Parser v2: author blocks of initials (initials-first and surname-first) before the title."""

import pytest

from factory.references.parse import parse_entry_fields


@pytest.mark.parametrize(
    ("text", "author", "title", "venue"),
    [
        (
            "I. Alabdulmohsin and A. P. Steiner A tale of two structures: how things work. "
            "In ICML, 2024.",
            "Alabdulmohsin",
            "A tale of two structures: how things work",
            "In ICML",
        ),
        (
            "J. Baek, S. K. Jauhar, S. Cucerzan, and S. J. Hwang ResearchAgent: iterative "
            "research idea generation. In Proceedings of NAACL, 2025.",
            "Baek",
            "ResearchAgent: iterative research idea generation",
            "In Proceedings of NAACL",
        ),
        (
            "V. Akinwande and J. Z. Kolter. Acceleratedlingam: Learning causal dags at the "
            "speed of gpus. arXiv preprint arXiv:2403.03772, 2024.",
            "Akinwande",
            "Acceleratedlingam: Learning causal dags at the speed of gpus",
            "arXiv preprint",
        ),
        (
            "C. F. Aliferis, I. Tsamardinos, and A. Statnikov. Hiton: a novel markov blanket "
            "algorithm. In AMIA annual symposium proceedings, page 21, 2003.",
            "Aliferis",
            "Hiton: a novel markov blanket algorithm",
            "In AMIA annual symposium proceedings, page 21",
        ),
        (
            "[12] X. Wang, B. Li, Y. Song, J. Singh, et al. Openhands: an open platform for "
            "agents. arXiv preprint, 2024.",
            "Wang",
            "Openhands: an open platform for agents",
            "arXiv preprint",
        ),
        (
            "Chen, Z., Lu, R., Zhao, A., and Huang, G. Does reinforcement learning really "
            "incentivize reasoning. arXiv preprint, 2025.",
            "Chen",
            "Does reinforcement learning really incentivize reasoning",
            "arXiv preprint",
        ),
        (
            "Meehl, G. A., Senior, C.A., Schlund, M.: Context for interpreting climate "
            "sensitivity. Journal of Climate 33, 2020.",
            "Meehl",
            "Context for interpreting climate sensitivity",
            "Journal of Climate 33",
        ),
        (
            "M. Cemri, S. van der Schaar Continuous-time modeling of outcomes. Nature, 2021.",
            "Cemri",
            "Continuous-time modeling of outcomes",
            "Nature",
        ),
        (
            "Y. Wang, W. E, and S. Chen. Scimaster: towards general science. arXiv, 2025.",
            "Wang",
            "Scimaster: towards general science",
            "arXiv",
        ),
        (
            "Eyring, V., Van Vuuren, D.P., et al.: The scenario model intercomparison. "
            "Geosci. Model Dev., 2016.",
            "Eyring",
            "The scenario model intercomparison",
            "Geosci",
        ),
    ],
)
def test_initials_author_blocks_split_before_the_title(
    text: str, author: str, title: str, venue: str
) -> None:
    f = parse_entry_fields(text)
    assert (f.first_author, f.title, f.venue) == (author, title, venue)


def test_author_block_without_a_title_after_it_never_yields_an_initial_as_title() -> None:
    f = parse_entry_fields("A. Smith and B. Jones.")
    assert f.title not in {"A", "B"}
