/**
 * Standalone NADOC debug snippet — paste directly into browser DevTools.
 * No dependency on app globals or module loading state.
 *
 * Usage: copy the block below, paste into DevTools console, press Enter.
 */

// ─── PASTE BELOW THIS LINE ────────────────────────────────────────────────────
;(async () => {
  console.group('%cNADOC Debug Snapshot', 'color:#58a6ff;font-weight:bold')

  // ── localStorage ─────────────────────────────────────────────────────────
  console.group('localStorage / sessionStorage')
  console.log('nadoc:mode (session):', sessionStorage.getItem('nadoc:mode'))
  ;['nadoc:workspace-path', 'nadoc:assembly-workspace-path']
    .forEach(k => console.log(k + ':', localStorage.getItem(k)))
  try {
    const d = JSON.parse(localStorage.getItem('nadoc:design') || 'null')
    console.log('cached design:', d
      ? { id: d.id, name: d.metadata?.name, helices: d.helices?.length, strands: d.strands?.length }
      : null)
  } catch { console.warn('cached design: PARSE ERROR') }
  try {
    const a = JSON.parse(localStorage.getItem('nadoc:assembly') || 'null')
    console.log('cached assembly:', a
      ? { name: a.metadata?.name, instances: a.instances?.length }
      : null)
    if (a?.instances?.length) {
      console.log('  instance sources:', a.instances.map(i => ({
        id:   i.id,
        name: i.name,
        src:  i.source?.type === 'file'
          ? 'file:' + i.source.path
          : 'inline:' + (i.source?.design?.id ?? '?'),
      })))
    }
  } catch { console.warn('cached assembly: PARSE ERROR') }
  console.groupEnd()

  // ── Live API ──────────────────────────────────────────────────────────────
  console.group('Live API')
  for (const url of ['/api/design', '/api/assembly']) {
    try {
      const r    = await fetch(url)
      const body = await r.json().catch(() => null)
      if (!r.ok) {
        console.log(url + ' →', r.status, r.statusText,
          r.status === 404 ? '(nothing loaded — normal in assembly mode)' : '')
      } else if (url.includes('assembly') && body?.assembly) {
        const a = body.assembly
        console.log(url + ' → ok', {
          name: a.metadata?.name,
          instances: a.instances?.length,
          sources: a.instances?.map(i => ({
            id:   i.id,
            name: i.name,
            src:  i.source?.type === 'file'
              ? 'file:' + i.source.path
              : 'inline:' + (i.source?.design?.id ?? '?'),
          })),
        })
      } else if (body?.design) {
        const d = body.design
        console.log(url + ' → ok', {
          id: d.id, name: d.metadata?.name,
          helices: d.helices?.length, strands: d.strands?.length,
        })
      } else {
        console.log(url + ' → ok', body)
      }
    } catch (e) {
      console.warn(url + ' → network error:', e)
    }
  }
  console.groupEnd()

  // ── Window globals ────────────────────────────────────────────────────────
  console.group('window globals')
  console.log('nadocDebug   defined?', typeof window.nadocDebug !== 'undefined')
  console.log('_nadocDebug  defined?', typeof window._nadocDebug !== 'undefined')
  console.groupEnd()

  console.groupEnd()
  return 'done'
})()
// ─── PASTE ABOVE THIS LINE ────────────────────────────────────────────────────
