/* Findings page (stub; the port replaces this file only). */
HUB.load(['shell', 'findings']).then(d => {
  const H = HUB.init(d.shell);
  H.mount({ page: 'findings', crumb: 'Findings' });
  H.$('#main').innerHTML = H.header({ title: 'Findings', level: 1 }) + '<p class="meta">This page is being built.</p>';
}).catch(e => {
  document.body.textContent = 'Findings failed to load: ' + e.message;
});
