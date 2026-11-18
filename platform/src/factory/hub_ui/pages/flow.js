/* Flow page (stub; the port replaces this file only). */
HUB.load(['shell', 'flow', 'screening', 'journeys']).then(d => {
  const H = HUB.init(d.shell);
  H.mount({ page: 'flow', crumb: 'Flow' });
  H.$('#main').innerHTML = H.header({ title: 'Flow', level: 1 }) + '<p class="meta">This page is being built.</p>';
}).catch(e => {
  document.body.textContent = 'Flow failed to load: ' + e.message;
});
