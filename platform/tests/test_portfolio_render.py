"""The portfolio renderers: Markdown and one self-contained HTML file, from the model only."""

from datetime import UTC, datetime

from factory.cli.portfolio_render import render_html, render_markdown
from factory.model.project import RigorMode
from factory.model.protocol import ProtocolStatus
from factory.services.human_queue import Gate, HumanItem, HumanQueue
from factory.services.portfolio import Portfolio, PortfolioRow, Stage

AS_OF = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
DISAGREEMENTS = "factory --project alpha-ta screen disagreements --stage title-abstract"
HOSTILE = "<script>alert(1)</script>&\"'"


def _sample() -> Portfolio:
    waiting = PortfolioRow(
        slug="alpha-ta",
        rigor_mode=RigorMode.PILOT,
        question_id="qst_1",
        protocol_id="prt_1",
        protocol_status=ProtocolStatus.READY,
        press="confirmed",
        stage=Stage.TA_SCREENING,
        tasks_open=4,
        tasks_claimed=1,
        tasks_expired=0,
        works=49,
        ta_included=7,
        ft_included=0,
        last_event_at=datetime(2026, 11, 4, 8, 0, tzinfo=UTC),
        last_search_at=datetime(2026, 10, 24, 9, 0, tzinfo=UTC),
        human=HumanQueue(
            items=[
                HumanItem(
                    gate=Gate.SCREENING_DISAGREEMENTS,
                    stage="title-abstract",
                    count=3,
                    command=DISAGREEMENTS,
                ),
                HumanItem(
                    gate=Gate.EXTRACTION_AUDIT,
                    stage=None,
                    count=12,
                    command="factory --project alpha-ta extract audit-label <audit-id>",
                ),
            ]
        ),
    )
    idle = PortfolioRow(slug="bravo-scoping", rigor_mode=RigorMode.EXPLORATORY, stage=Stage.SCOPING)
    return Portfolio(generated_at=AS_OF, projects=[waiting, idle])


MARKDOWN = """# Portfolio

As of 2026-11-05T09:00:00Z. 2 projects.

| Project | Mode | Stage | Works | TA included | FT included | Tasks open/claimed/expired | Last search | Waiting on you |
| --- | --- | --- | ---: | ---: | ---: | --- | --- | ---: |
| alpha-ta | pilot | ta-screening | 49 | 7 | 0 | 4/1/0 | 12 days ago | 15 |
| bravo-scoping | exploratory | scoping | 0 | 0 | 0 | 0/0/0 | never | 0 |

## Waiting on you

### alpha-ta

- screening-disagreements (title-abstract): 3. `factory --project alpha-ta screen disagreements --stage title-abstract`
- extraction-audit: 12. `factory --project alpha-ta extract audit-label <audit-id>`
"""  # noqa: E501


def test_markdown_snapshot() -> None:
    assert render_markdown(_sample(), AS_OF) == MARKDOWN


def test_markdown_lists_an_unreadable_project_by_error_class() -> None:
    broken = Portfolio(
        generated_at=AS_OF, projects=[PortfolioRow(slug="delta", error="EventLogError")]
    )
    text = render_markdown(broken, AS_OF)
    assert "| delta | n/a | error: EventLogError |" in text
    assert "## Waiting on you" not in text


def test_markdown_without_waiting_items_says_so() -> None:
    idle = Portfolio(
        generated_at=AS_OF,
        projects=[PortfolioRow(slug="bravo-scoping", stage=Stage.SCOPING)],
    )
    assert "Nothing is waiting on you." in render_markdown(idle, AS_OF)


def test_html_is_one_document_without_script() -> None:
    html = render_html(_sample(), AS_OF)
    assert html.startswith("<!doctype html>")
    assert "<script" not in html.lower()
    assert "prefers-color-scheme: dark" in html
    assert "<style>" in html and "http" not in html.replace("http-equiv", "")
    assert "alpha-ta" in html and "12 days ago" in html


def test_html_escapes_every_value() -> None:
    hostile = Portfolio(
        generated_at=AS_OF,
        projects=[
            PortfolioRow(slug="delta", error=HOSTILE),
            PortfolioRow(
                slug="echo",
                stage=Stage.SEARCH,
                human=HumanQueue(
                    items=[
                        HumanItem(
                            gate=Gate.PRESS_CONFIRMATION, stage=None, count=1, command=HOSTILE
                        )
                    ]
                ),
            ),
        ],
    )
    html = render_html(hostile, AS_OF)
    assert "<script" not in html.lower()
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_renderers_are_deterministic() -> None:
    assert render_html(_sample(), AS_OF) == render_html(_sample(), AS_OF)
    assert render_markdown(_sample(), AS_OF) == render_markdown(_sample(), AS_OF)


def test_ages_come_from_as_of_not_the_clock() -> None:
    later = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
    assert "27 days ago" in render_markdown(_sample(), later)
