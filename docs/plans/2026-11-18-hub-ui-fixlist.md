# Hub v2 fix list (collected from build reports; worked in the fix round)

1. Journeys: "references extracted" and "cited by corpus" stops not fed (`extra`); stops carry no event id (TrailStep lacks it); trace ids only for screening.
2. Lenses payload: `adoption.cells` empty on the pilot build (adoption records not reaching lenses); chain and adoption cells carry no work ids; only one matrix pair server-side (JS computes the others: move to the service, all pairs of the DNA dims); icicle lacks dimension names.
3. Findings: no full value distributions for the no_human, full_lifecycle, iterative_loop and compare cards; stage rows lack per-paper quotes; rule titles typed in the page (move to the payload).
4. Overview: hero has empty space under the lead; Corpus must accept `#layer=`, `#human=`, `#year=` (links from composition and growth).
5. 390 px layout: charts look cropped on the right in headless shots; check in a real browser.
6. The real browser has never been used for hover, click, drawer or Ctrl-K: step 12 smoke plus the live check.
7. Not all theme shots were read by every port agent (overview: gruvbox and lcars; findings: light, gruvbox, lcars and 390): review all themes.
8. Mining: the code-release denominator differs from the demo; per-row model not tracked; the grid shows the first value plus n for multi-row miners.
9. `python -m factory.cli.main` has no `__main__` guard (pre-existing, not ours; note only).
10. TDD: steps 3 and 8b wrote tests after the code (reported honestly); the review adds guard mutation on those modules.
11. Explore: the payload has no `methods` (ⓘ texts typed in the page) and no per-work similarity (JS computes R4; move it to `hub_lenses.similar` in the payload); "unlayered" is missing from the layer order.
12. Miners: `population` says `included-ft` for core-only miners (compute the real scope name and n); the by-model rate covers all miners, not each one; fields carry no descriptions; there are no paper lists per value; platform rates are null for most miners; a local field-label map (move it to the shared LABELS).
