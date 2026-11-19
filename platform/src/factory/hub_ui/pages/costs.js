/* Costs & runs page (stub of step 0: the port fills it in). Payload: costs. Until then each old-hub product it
   will replace stays reachable through a link. */
HUB.load(['shell', 'costs']).then(d => {
  const H = HUB.init(d.shell);
  const main = H.mount({ page: 'costs', crumb: 'Costs & runs' });
  const { esc } = H;
  const old = [['Costs', '../#costs'], ['Runs', '../#runs']];
  main.innerHTML = H.header({ title: 'Costs & runs', sub: 'What the work cost and which runs produced it.', level: 1 }) +
    '<p class="meta" role="status">This page is being ported.</p>' +
    '<p class="meta">Meanwhile, in the classic hub: ' +
    old.map(([label, href]) => '<a href="' + esc(href) + '">' + esc(label) + '</a>').join(', ') + '.</p>';
});
