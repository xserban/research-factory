/* Protocol page (stub of step 0: the port fills it in). Payload: protocol. Until then each old-hub product it
   will replace stays reachable through a link. */
HUB.load(['shell', 'protocol']).then(d => {
  const H = HUB.init(d.shell);
  const main = H.mount({ page: 'protocol', crumb: 'Protocol' });
  const { esc } = H;
  const old = [['Protocol', '../#protocol'], ['Decisions', '../#decisions'], ['PRESS', '../#press'], ['Probes', '../#probes']];
  main.innerHTML = H.header({ title: 'Protocol', sub: 'The registered plan, its decisions, PRESS review and probes.', level: 1 }) +
    '<p class="meta" role="status">This page is being ported.</p>' +
    '<p class="meta">Meanwhile, in the classic hub: ' +
    old.map(([label, href]) => '<a href="' + esc(href) + '">' + esc(label) + '</a>').join(', ') + '.</p>';
});
