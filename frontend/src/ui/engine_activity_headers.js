/**
 * engine_activity_headers.js — lights a spinning indicator on the sidebar section
 * header of every simulation engine that currently has a running/preparing job,
 * so the user can tell at a glance which engine is busy (even with the panel
 * collapsed).
 *
 * One poll of GET /api/jobs/active (via {@link fetchActiveJobs}) covers all five
 * engines; {@link runningEngines} maps the result to the set of busy engines and
 * we toggle a reused `.nadoc-spinner` on each header. Purely a display aid — it
 * owns no job state and never launches or reconciles anything.
 */

import { fetchActiveJobs as defaultFetch, runningEngines } from './job_activity.js'

/** activity engine key → { tab, label } for the engine-selector TAB it annotates.
 *  The per-engine section headers were removed, so the busy spinner now hangs on the
 *  tab (next to its label). Note the tab key is 'namd' where the job key is 'md';
 *  LAMMPS has no tab (folded into oxDNA's CPU fallback) → no spinner. */
const ENGINE_HEADERS = [
  { engine: 'oxdna',  tab: 'oxdna', label: 'An oxDNA' },
  { engine: 'mrdna',  tab: 'mrdna', label: 'An mrDNA' },
  { engine: 'cando',  tab: 'cando', label: 'A CanDo FEM' },
  { engine: 'md',     tab: 'namd',  label: 'A molecular-dynamics' },
]

/**
 * Wire the per-engine header spinners.
 *
 * @param {object}   [opts]
 * @param {Function} [opts.fetchActiveJobs] async () => activeJobs[] (default: shared)
 * @param {number}   [opts.intervalMs=4000] poll period
 * @param {Document} [opts.doc=document]    DOM root (injectable for tests)
 * @returns {{refresh: () => Promise<void>, stop: () => void}}
 */
export function initEngineActivityHeaders({
  fetchActiveJobs = defaultFetch,
  intervalMs = 4000,
  doc = document,
} = {}) {
  // Insert one hidden spinner into each engine's TAB, once.
  const spinners = new Map()   // engine → spinner span (or null if tab absent)
  for (const { engine, tab, label } of ENGINE_HEADERS) {
    const btn = doc.querySelector(`.engine-selector-btn[data-engine="${tab}"]`)
    if (!btn) { spinners.set(engine, null); continue }
    const sp = doc.createElement('span')
    sp.className = 'nadoc-spinner'
    sp.style.marginLeft = '4px'
    sp.hidden = true
    sp.title = `${label} simulation is running`
    sp.setAttribute('data-engine-spinner', engine)
    btn.appendChild(sp)
    spinners.set(engine, sp)
  }

  function apply(running) {
    for (const [engine, sp] of spinners) {
      if (sp) sp.hidden = !running.has(engine)
    }
  }

  async function refresh() {
    apply(runningEngines(await fetchActiveJobs()))
  }

  // Skip polling while the tab is hidden (nothing to see; saves the reconcile scan).
  const tick = () => { if (!doc.hidden) refresh() }
  const timer = setInterval(tick, intervalMs)
  refresh()   // paint immediately on load

  return {
    refresh,
    stop() { clearInterval(timer) },
  }
}
