/* Method page (stub of step 0: the port fills it in). Payload: method. Until then each old-hub product it
   will replace stays reachable through a link. */
HUB.load(['shell', 'method']).then(d => {
  const H = HUB.init(d.shell);
  const main = H.mount({ page: 'method', crumb: 'Method' });
  const { esc } = H;
  const old = [['Lifecycle', '../#lifecycle'], ['Steps', '../#steps'], ['Taxonomy', '../#taxonomy']];
  main.innerHTML = H.header({ title: 'Method', sub: 'Lifecycle, steps and taxonomy.', level: 1 }) +
    '<p class="meta" role="status">This page is being ported.</p>' +
    '<p class="meta">Meanwhile, in the classic hub: ' +
    old.map(([label, href]) => '<a href="' + esc(href) + '">' + esc(label) + '</a>').join(', ') + '.</p>';
});
