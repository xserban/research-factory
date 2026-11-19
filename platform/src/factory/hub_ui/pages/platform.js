/* Platform page (stub of step 0: the port fills it in). Payload: platform. Until then each old-hub product it
   will replace stays reachable through a link. */
HUB.load(['shell', 'platform']).then(d => {
  const H = HUB.init(d.shell);
  const main = H.mount({ page: 'platform', crumb: 'Platform' });
  const { esc } = H;
  const old = [['Capabilities', '../#capabilities'], ['Backlog', '../backlog/']];
  main.innerHTML = H.header({ title: 'Platform', sub: 'What the platform can do, and its backlog.', level: 1 }) +
    '<p class="meta" role="status">This page is being ported.</p>' +
    '<p class="meta">Meanwhile, in the classic hub: ' +
    old.map(([label, href]) => '<a href="' + esc(href) + '">' + esc(label) + '</a>').join(', ') + '.</p>';
});
