/* Write & export page (stub of step 0: the port fills it in). Payload: write. Until then each old-hub product it
   will replace stays reachable through a link. */
HUB.load(['shell', 'write']).then(d => {
  const H = HUB.init(d.shell);
  const main = H.mount({ page: 'write', crumb: 'Write & export' });
  const { esc } = H;
  const old = [['Synthesis', '../#synthesis'], ['Bibliography', '../#bibliography'], ['Wiki vault', '../#wiki']];
  main.innerHTML = H.header({ title: 'Write & export', sub: 'Synthesis pages, bibliography, wiki vault and the PRISMA diagram.', level: 1 }) +
    '<p class="meta" role="status">This page is being ported.</p>' +
    '<p class="meta">Meanwhile, in the classic hub: ' +
    old.map(([label, href]) => '<a href="' + esc(href) + '">' + esc(label) + '</a>').join(', ') + '.</p>';
});
