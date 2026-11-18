/* Explore page (stub; the port replaces this file only). */
HUB.load(['shell', 'explore']).then(d => {
  const H = HUB.init(d.shell);
  H.mount({ page: 'explore', crumb: 'Explore' });
  H.$('#main').innerHTML = H.header({ title: 'Explore', level: 1 }) + '<p class="meta">This page is being built.</p>';
}).catch(e => {
  document.body.textContent = 'Explore failed to load: ' + e.message;
});
