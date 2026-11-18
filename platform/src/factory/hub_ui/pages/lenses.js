/* Lenses page (stub; the port replaces this file only). */
HUB.load(['shell', 'lenses']).then(d => {
  const H = HUB.init(d.shell);
  H.mount({ page: 'lenses', crumb: 'Lenses' });
  H.$('#main').innerHTML = H.header({ title: 'Lenses', level: 1 }) + '<p class="meta">This page is being built.</p>';
}).catch(e => {
  document.body.textContent = 'Lenses failed to load: ' + e.message;
});
