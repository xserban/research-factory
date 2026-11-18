/* Living review page (stub; the port replaces this file only). */
HUB.load(['shell', 'living']).then(d => {
  const H = HUB.init(d.shell);
  H.mount({ page: 'living', crumb: 'Living review' });
  H.$('#main').innerHTML = H.header({ title: 'Living review', level: 1 }) + '<p class="meta">This page is being built.</p>';
}).catch(e => {
  document.body.textContent = 'Living review failed to load: ' + e.message;
});
