/* Miners page (stub; the port replaces this file only). */
HUB.load(['shell', 'mining']).then(d => {
  const H = HUB.init(d.shell);
  H.mount({ page: 'miners', crumb: 'Miners' });
  H.$('#main').innerHTML = H.header({ title: 'Miners', level: 1 }) + '<p class="meta">This page is being built.</p>';
}).catch(e => {
  document.body.textContent = 'Miners failed to load: ' + e.message;
});
