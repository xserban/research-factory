/* Pipeline page (stub of step 0: the port fills it in). Payload: pipeline. Until then each old-hub product it
   will replace stays reachable through a link. */
HUB.load(['shell', 'pipeline']).then(d => {
  const H = HUB.init(d.shell);
  const main = H.mount({ page: 'pipeline', crumb: 'Pipeline' });
  const { esc } = H;
  const old = [['Work queue', '../#queue'], ['Control room', '../#home'], ['Activity', '../#activity']];
  main.innerHTML = H.header({ title: 'Pipeline', sub: 'Where the work stands and what runs next.', level: 1 }) +
    '<p class="meta" role="status">This page is being ported.</p>' +
    '<p class="meta">Meanwhile, in the classic hub: ' +
    old.map(([label, href]) => '<a href="' + esc(href) + '">' + esc(label) + '</a>').join(', ') + '.</p>';
});
