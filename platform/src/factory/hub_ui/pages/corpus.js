/* Corpus page (stub; the port replaces this file only). */
HUB.load(['shell', 'corpus']).then(d => {
  const H = HUB.init(d.shell);
  H.mount({ page: 'corpus', crumb: 'Corpus' });
  H.$('#main').innerHTML = H.header({ title: 'Corpus', level: 1 }) + '<p class="meta">This page is being built.</p>';
}).catch(e => {
  document.body.textContent = 'Corpus failed to load: ' + e.message;
});
