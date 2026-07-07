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

/** engine key → { headingId, label } for the section header it annotates. */
const ENGINE_HEADERS = [
  { engine: 'oxdna',  headingId: 'oxdna-jobs-heading',    label: 'An oxDNA' },
  { engine: 'lammps', headingId: 'lammps-jobs-heading',   label: 'A LAMMPS' },
  { engine: 'mrdna',  headingId: 'mrdna-jobs-heading',    label: 'An mrDNA' },
  { engine: 'cando',  headingId: 'cando-jobs-heading',    label: 'A CanDo FEM' },
  { engine: 'md',     headingId: 'md-jobs-panel-heading', label: 'A molecular-dynamics' },
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
  // Insert one hidden spinner into each engine's header title, once.
  const spinners = new Map()   // engine → spinner span (or null if header absent)
  for (const { engine, headingId, label } of ENGINE_HEADERS) {
    const heading = doc.getElementById(headingId)
    const title = heading?.querySelector('span')   // the title span (arrow is a later sibling)
    if (!title) { spinners.set(engine, null); continue }
    const sp = doc.createElement('span')
    sp.className = 'nadoc-spinner'
    sp.style.marginLeft = '8px'
    sp.hidden = true
    sp.title = `${label} simulation is running`
    sp.setAttribute('data-engine-spinner', engine)
    title.appendChild(sp)
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
