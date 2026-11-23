# ruff: noqa: E501
"""The main hub's factory feed pages (`/feed/`, `/feed/project/<slug>/`, `/feed/liked/`,
`/feed/reading/`), in the hub v2 design system (kit.css tokens, fonts, buttons, chips, info panels).

Invariants:
- Pure string functions over already-read values: nothing is read or written here, no model is
  called. Every value from outside is HTML-escaped.
- Server-rendered: a page is one GET; the script (`hub_ui/feed.js`) only writes (reactions, train,
  send, add) and filters what is on the page. The weak line only decides which badges show and where
  the divider sits; it hides no card.
- The hub token is in `<meta name='factory-token'>`, as on the other main-hub pages; a project's
  token goes only into the project list the picker uses.
- The page works without the factory feed environment: it then says the feed is off and links the
  classic page, so `/feed/` is never an error.
- The assets are `kit.css`, its fonts, `feed.css` and `feed.js`; `asset` serves nothing else.
"""

from __future__ import annotations

import html
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from typing import Final

from factory.services import hub_ui
from factory.services.factory_feed import FeedCard, FeedCounts, ProjectBadge, TodayPage
from factory.services.factory_feed_actions import RankerStatus
from factory.services.site_chrome import with_bar

ASSET_PREFIX: Final = "/feed/assets/"
WINDOWS: Final[tuple[tuple[str, str, int | None], ...]] = (
    ("24h", "Last 24 hours", 1),
    ("7d", "Last 7 days", 7),
    ("30d", "Last 30 days", 30),
    ("all", "All", None),
)
DEFAULT_WINDOW: Final = "7d"

_OWN: Final = {
    "feed.css": ("hub_ui/feed.css", "text/css; charset=utf-8"),
    "feed.js": ("hub_ui/feed.js", "text/javascript; charset=utf-8"),
}


def asset(name: str) -> tuple[bytes, str] | None:
    """(body, content type) of a served asset of the feed page, or None for any other name."""
    if name in _OWN:
        rel, kind = _OWN[name]
        return resources.files("factory").joinpath(*rel.split("/")).read_bytes(), kind
    if (name == "kit.css" or name.startswith("fonts/")) and name in hub_ui.ASSETS:
        return hub_ui.asset_bytes(name), hub_ui.ASSETS[name][1]
    return None


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


@dataclass(frozen=True)
class ProjectInfo:
    """A project with a feed configuration: its page link, picker entry and categories."""

    slug: str
    title: str
    token: str
    categories: tuple[str, ...]


@dataclass(frozen=True)
class PageContext:
    hub_token: str
    projects: tuple[ProjectInfo, ...]
    counts: FeedCounts
    status: RankerStatus
    ranking_id: str | None


def _info(text: str, label: str = "About this") -> str:
    return (
        f"<button type=button class=info data-tip='{_e(text)}' aria-label='{_e(label)}'>i</button>"
    )


def _authors(authors: Sequence[str]) -> str:
    shown = ", ".join(_e(a) for a in authors[:3])
    more = len(authors) - 3
    return shown + (f" +{more}" if more > 0 else "")


def _badge(b: ProjectBadge) -> str:
    slug = _e(b.slug)
    href = f"/feed/project/{slug}/"
    if b.score == 0.0 and b.held:
        return f"<a class=chip data-held data-score='0' href='{href}'>in {slug}</a>"
    held = " data-held" if b.held else ""
    label = f"{slug} {round(b.score * 100)}%" + (" · in project" if b.held else "")
    tip = f"similar to {b.closest_title or b.closest_core_work}"
    return f"<a class=chip{held} data-score='{b.score:.4f}' href='{href}' title='{_e(tip)}'>{label}</a>"


def _card(card: FeedCard, *, project: str | None = None, rank: int | None = None) -> str:
    entry = _e(card.entry_id)
    date = _e((card.submitted or "")[:10])
    badge = next((b for b in card.badges if b.slug == project), None) if project else None
    score_attr = f" data-score='{badge.score:.4f}'" if badge is not None else ""
    pred = f" data-pred='{card.score:.4f}'" if card.score is not None else ""
    rank_attr = f" data-rank='{card.rank}'" if card.rank is not None else ""
    text = _e(f"{card.title} {' '.join(card.authors)} {card.entry_id}")
    cats = _e(" ".join(card.categories))
    shown_rank = rank if rank is not None else card.rank
    top = (
        (f"<span class=fx-rank>#{shown_rank}</span>" if shown_rank is not None else "")
        + f"<a class=fx-title href='https://arxiv.org/abs/{entry}'>{_e(card.title or card.entry_id)}</a>"
    )
    meta = f"<span class=mono>{entry}</span> · {date or 'undated'} · {_authors(card.authors) or 'no authors listed'}"
    badges = "".join(_badge(b) for b in card.badges)
    if card.explore:
        badges += "<span class='chip explore' title='picked by the exploration share, not by rank'>explore</span>"
    sim = ""
    if badge is not None and (badge.closest_title or badge.closest_core_work):
        sim = f"<p class='meta fx-sim'>similar to {_e(badge.closest_title or badge.closest_core_work)} · {badge.score:.3f}</p>"
    pred_line = ""
    if card.score is not None and card.ranker_version is not None:
        pred_line = f"<p class='meta fx-pred'>predicted {round(card.score * 100)}% (ranker v{card.ranker_version})</p>"
    cat_html = "".join(
        f"<button type=button class=fx-cat data-cat='{_e(c)}'>{_e(c)}</button>"
        for c in card.categories
    )
    liked, disliked = card.label == "like", card.label == "dislike"
    save_next = "unsave" if card.saved else "save"
    acts = (
        f"<button type=button class=btn data-act=like aria-pressed={'true' if liked else 'false'}>Like</button>"
        f"<button type=button class=btn data-act=dislike aria-pressed={'true' if disliked else 'false'}>Dislike</button>"
        f"<button type=button class=btn data-act=save data-next={save_next} aria-pressed={'true' if card.saved else 'false'}>{'Saved' if card.saved else 'Save'}</button>"
        "<button type=button class=btn data-act=send>Send to project…</button>"
        "<button type=button class=btn data-act=add>Add to project…</button>"
    )
    more = (
        "<button type=button class=fx-more aria-expanded=false>Show more</button>"
        if card.abstract
        else ""
    )
    return (
        f"<article class='card fx-card' data-entry-id='{entry}'{rank_attr}{score_attr}{pred} data-text='{text}' data-cats='{cats}'>"
        f"<div class=fx-top>{top}</div><div class='meta fx-meta'>{meta}</div>"
        f"<div class=fx-badges>{badges}</div>{sim}"
        + (f"<p class=fx-abs>{_e(card.abstract)}</p>{more}" if card.abstract else "")
        + f"{pred_line}<div class=fx-cats>{cat_html}</div><div class=fx-acts>{acts}</div></article>"
    )


def _sidebar(ctx: PageContext, active: str, cards: Sequence[FeedCard]) -> str:
    def link(key: str, href: str, label: str, count: int | None) -> str:
        cur = " aria-current=page" if key == active else ""
        n = f"<span class=n data-count='{key}'>{count}</span>" if count is not None else ""
        return f"<a href='{href}'{cur}>{label}{n}</a>"

    c = ctx.counts
    projects = (
        "".join(
            f"<a href='/feed/project/{_e(p.slug)}/'{' aria-current=page' if active == 'project:' + p.slug else ''}>{_e(p.title or p.slug)}</a>"
            for p in ctx.projects
        )
        or "<span class=note>No project has a feed configuration.</span>"
    )
    cats = Counter(cat for card in cards for cat in card.categories)
    chips = "".join(
        f"<button type=button class=chip data-cat='{_e(k)}' aria-pressed=false>{_e(k)} <span class=n>{n}</span></button>"
        for k, n in sorted(cats.items(), key=lambda kv: (-kv[1], kv[0]))[:24]
    )
    return (
        "<aside class=fx-side aria-label='Feed'><nav>"
        + link("today", "/feed/", "Today", c.today)
        + link("liked", "/feed/liked/", "Liked", c.liked)
        + link("reading", "/feed/reading/", "Reading list", c.reading)
        + f"</nav><h2>Projects {_info('A project is on this list when it has a feed configuration. Its page orders the pool by similarity to its core works.', 'About projects')}</h2><nav>{projects}</nav>"
        + (f"<h2>Categories</h2><div class=fx-chips>{chips}</div>" if chips else "")
        + "<h2>Other</h2><nav><a href='/feed/classic/'>Classic view</a></nav></aside>"
    )


def _settings(ctx: PageContext) -> str:
    st = ctx.status
    state = (
        f"ranker v{st.version}, trained {_e(st.trained_at or '')} on {st.trained_likes} likes and {st.trained_dislikes} dislikes"
        if st.version is not None
        else "not trained yet: Today is ordered newest first"
    )
    reason = (
        ""
        if st.can_train
        else f"<p class=note id=fx-train-reason>{_e(st.reason or 'Training is not possible yet.')}</p>"
    )
    disabled = "" if st.can_train else " disabled"
    cats = "".join(
        f"<dt>{_e(p.title or p.slug)}</dt><dd>{', '.join(_e(c) for c in p.categories) or 'none'}</dd>"
        for p in ctx.projects
    )
    return (
        "<section class='card raised fx-settings' id=fx-settings hidden aria-label=Settings>"
        f"<h2>Settings {_info('The weak line only decides which project badges show on a card. It hides nothing. It is kept in this browser.', 'About the weak line')}</h2>"
        "<label>Weak line <input type=range id=fx-weak min=0 max=1 step=0.05 value=0.5> <span class=mono id=fx-weak-out>0.50</span></label>"
        f"<h2>Ranker {_info('One classifier learns from your likes and dislikes. It trains only when you press Train, on at least 5 reactions with at least 3 likes. Projects never learn: their score is similarity to their core works.', 'About the ranker')}</h2>"
        f"<dl><dt>State</dt><dd>{state}</dd><dt>Reactions now</dt><dd>{st.likes} likes, {st.dislikes} dislikes</dd></dl>"
        f"<button type=button class='btn primary' id=fx-train{disabled}>Train</button> <span class=note id=fx-train-out></span>{reason}"
        "<h2>Categories</h2><dl>" + cats + "</dl>"
        "<p class=note>Read only. Change them with <span class=mono>factory feed configure</span>.</p></section>"
    )


def _shell(
    ctx: PageContext, active: str, title: str, body: str, cards: Sequence[FeedCard], page: str
) -> str:
    projects = json.dumps(
        [{"slug": p.slug, "title": p.title, "token": p.token} for p in ctx.projects]
    )
    v = _e(hub_ui.asset_version())
    head = (
        f"<meta name='factory-token' content='{_e(ctx.hub_token)}'>"
        "<meta charset=utf-8><meta name=viewport content='width=device-width, initial-scale=1'>"
        f"<link rel=stylesheet href='{ASSET_PREFIX}kit.css?v={v}'><link rel=stylesheet href='{ASSET_PREFIX}feed.css?v={v}'>"
    )
    doc = (
        f"<!doctype html><html lang=en><head><title>{_e(title)}</title>{head}</head><body>"
        f"<div class=fx id=fx data-page='{page}' data-projects='{_e(projects)}'"
        + (f" data-ranking-id='{_e(ctx.ranking_id)}'" if ctx.ranking_id else "")
        + f">{_sidebar(ctx, active, cards)}<main>{body}</main></div>"
        f"<script src='{ASSET_PREFIX}feed.js?v={v}'></script></body></html>"
    )
    return with_bar(doc, "feed")


def _head(title: str, info: str, extra: str = "") -> str:
    return (
        f"<div class=fx-head><h1>{_e(title)} {_info(info, 'About ' + title)}</h1>{extra}"
        "<button type=button class=btn id=fx-gear aria-expanded=false>Settings</button></div>"
    )


def _tools(sort_html: str = "") -> str:
    return f"<div class=fx-tools>{sort_html}<input type=search id=fx-q placeholder='Filter this page' aria-label='Filter this page'></div>"


def render_today(ctx: PageContext, page: TodayPage) -> str:
    base = "/feed/"
    sort = "".join(
        f"<option value='{k}'{' selected' if page.sort == k else ''}>{label}</option>"
        for k, label in (("ranked", "Ranked"), ("newest", "Newest"))
    )
    sorter = f"<label>Sort <select id=fx-sort data-base='{base}'>{sort}</select></label>"
    nav = ""
    if page.pages > 1:
        prev = (
            f"<a class=btn href='{base}?sort={page.sort}&page={page.page - 1}'>Previous</a>"
            if page.page > 1
            else ""
        )
        nxt = (
            f"<a class=btn href='{base}?sort={page.sort}&page={page.page + 1}'>Next</a>"
            if page.page < page.pages
            else ""
        )
        nav = f"<div class=fx-pages>{prev}<span class=meta>Page {page.page} of {page.pages} · {page.total} papers</span>{nxt}</div>"
    cards = "".join(_card(c) for c in page.cards)
    ranker = (
        ""
        if ctx.status.version is not None
        else "<p class=note>No ranker yet: Today is newest first. Like or dislike some papers, then press Train in Settings.</p>"
    )
    empty = (
        ""
        if page.cards
        else "<p class=fx-empty>Nothing to show. Run a feed fetch, or you have reacted to everything.</p>"
    )
    body = (
        _head(
            "Today",
            "The papers the projects' feeds fetched, one list. Ranked uses the classifier trained on your likes and dislikes; a liked or disliked paper leaves this list.",
        )
        + _settings(ctx)
        + ranker
        + _tools(sorter)
        + f"<div class=fx-list>{cards}</div>{empty}{nav}"
    )
    return _shell(ctx, "today", "Today · New papers", body, page.cards, "today")


def render_project(
    ctx: PageContext, info: ProjectInfo, cards: Sequence[FeedCard], window: str
) -> str:
    base = f"/feed/project/{_e(info.slug)}/"
    opts = "".join(
        f"<option value='{k}'{' selected' if k == window else ''}>{label}</option>"
        for k, label, _ in WINDOWS
    )
    picker = f"<label>Window <select id=fx-window data-base='{base}'>{opts}</select></label>"
    items = "".join(_card(c, project=info.slug, rank=n) for n, c in enumerate(cards, 1))
    divider = "<div class=fx-div id=fx-divider hidden>weak matches below <span id=fx-divider-x>0.50</span></div>"
    empty = "" if cards else "<p class=fx-empty>No scored paper in this window.</p>"
    body = (
        _head(
            info.title or info.slug,
            "Papers ordered by their similarity to this project's core works, the highest first. The project does not learn from your reactions.",
        )
        + _settings(ctx)
        + _tools(picker)
        + f"<div class=fx-list>{items}{divider}</div>{empty}"
    )
    return _shell(
        ctx,
        f"project:{info.slug}",
        f"{info.title or info.slug} · New papers",
        body,
        cards,
        "project",
    )


def _row(card: FeedCard, was: str, act: str, label: str) -> str:
    entry = _e(card.entry_id)
    return (
        f"<div class='card fx-row' data-entry-id='{entry}' data-was='{was}' data-text='{_e(card.title + ' ' + card.entry_id)}' data-cats='{_e(' '.join(card.categories))}'>"
        f"<a class='grow fx-title' href='https://arxiv.org/abs/{entry}'>{_e(card.title or card.entry_id)}</a>"
        f"<span class='meta mono'>{_e((card.submitted or '')[:10])}</span>"
        f"<button type=button class=btn data-act={act}>{label}</button></div>"
    )


def render_liked(ctx: PageContext, liked: Sequence[FeedCard], disliked: Sequence[FeedCard]) -> str:
    rows = (
        "".join(_row(c, "liked", "undo", "Undo") for c in liked)
        or "<p class=fx-empty>Nothing liked yet.</p>"
    )
    dis = "".join(_row(c, "disliked", "undo", "Undo") for c in disliked)
    folded = (
        f"<details class=fx-disliked><summary>{len(disliked)} disliked</summary><div class=fx-list>{dis}</div></details>"
        if disliked
        else ""
    )
    body = (
        _head(
            "Liked",
            "Papers you liked, newest reaction first. Undo records a new reaction that supersedes the earlier one.",
        )
        + _settings(ctx)
        + f"<div class=fx-list>{rows}</div>{folded}"
    )
    return _shell(ctx, "liked", "Liked · New papers", body, [], "liked")


def render_reading(ctx: PageContext, cards: Sequence[FeedCard]) -> str:
    rows = (
        "".join(_row(c, "reading", "remove", "Remove") for c in cards)
        or "<p class=fx-empty>The reading list is empty.</p>"
    )
    body = (
        _head("Reading list", "Papers you saved, newest first. Remove records an unsave.")
        + _settings(ctx)
        + f"<div class=fx-list>{rows}</div>"
    )
    return _shell(ctx, "reading", "Reading list · New papers", body, [], "reading")


def render_off(hub_token: str) -> str:
    """The page when the hub runs without the factory feed: a notice and the classic page."""
    doc = (
        "<!doctype html><html lang=en><head><title>New papers</title>"
        f"<meta name='factory-token' content='{_e(hub_token)}'><meta charset=utf-8>"
        f"<link rel=stylesheet href='{ASSET_PREFIX}kit.css'></head><body><main style='padding:24px'>"
        "<h1>New papers</h1><p>The factory feed is off on this hub. "
        "<a href='/feed/classic/'>Open the classic view</a>.</p></main></body></html>"
    )
    return with_bar(doc, "feed")
