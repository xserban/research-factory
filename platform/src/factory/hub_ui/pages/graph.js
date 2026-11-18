/* Graph page (stub; the port replaces this file only). */
HUB.load(['shell', 'graph']).then(d => {
  const H = HUB.init(d.shell);
  H.mount({ page: 'graph', crumb: 'Graph' });
  H.$('#main').innerHTML = H.header({ title: 'Graph', level: 1 }) + '<p class="meta">This page is being built.</p>';
}).catch(e => {
  document.body.textContent = 'Graph failed to load: ' + e.message;
});
