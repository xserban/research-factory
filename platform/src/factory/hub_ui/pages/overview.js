/* Overview page (pipeline proof; the full port is a later step). Loads the shell and overview
   payloads, mounts the shell and writes the header and the lead sentence from the payload. */
HUB.load(['shell', 'overview']).then(d => {
  const H = HUB.init(d.shell);
  H.mount({ page: 'overview', crumb: 'Overview' });
  const lead = d.overview.lead;
  const sentence = `${H.fmt(lead.included)} papers are included, from ${H.fmt(lead.identified)} records identified and ${H.fmt(lead.screened)} screened; ${H.fmt(lead.read_in_full)} have been read in full.`;
  H.$('#main').innerHTML = H.header({ title: 'Overview', level: 1, sub: H.esc(sentence) });
}).catch(e => {
  document.body.textContent = 'Overview failed to load: ' + e.message;
});
