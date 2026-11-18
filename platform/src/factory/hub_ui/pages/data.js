/* Extracted data page (stub; the port replaces this file only). */
HUB.load(['shell', 'mining']).then(d => {
  const H = HUB.init(d.shell);
  H.mount({ page: 'data', crumb: 'Extracted data' });
  H.$('#main').innerHTML = H.header({ title: 'Extracted data', level: 1 }) + '<p class="meta">This page is being built.</p>';
}).catch(e => {
  document.body.textContent = 'Extracted data failed to load: ' + e.message;
});
