/* Brand kit page (stub; the port replaces this file only). */
HUB.load(['shell']).then(d => {
  const H = HUB.init(d.shell);
  H.mount({ page: 'kit', crumb: 'Brand kit' });
  H.$('#main').innerHTML = H.header({ title: 'Brand kit', level: 1 }) + '<p class="meta">This page is being built.</p>';
}).catch(e => {
  document.body.textContent = 'Brand kit failed to load: ' + e.message;
});
