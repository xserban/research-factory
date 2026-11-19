/* Sources page (stub of step 0: the port fills it in). Payload: sources. Until then each old-hub product it
   will replace stays reachable through a link. */
HUB.load(['shell', 'sources']).then(d => {
  const H = HUB.init(d.shell);
  const main = H.mount({ page: 'sources', crumb: 'Sources' });
  const { esc } = H;
  const old = [['Search and dedup', '../#search'], ['Acquisition', '../#acquisition'], ['Conversion', '../#conversion'], ['Documents', '../#documents']];
  main.innerHTML = H.header({ title: 'Sources', sub: 'Searches, acquisition, conversion and documents.', level: 1 }) +
    '<p class="meta" role="status">This page is being ported.</p>' +
    '<p class="meta">Meanwhile, in the classic hub: ' +
    old.map(([label, href]) => '<a href="' + esc(href) + '">' + esc(label) + '</a>').join(', ') + '.</p>';
});
