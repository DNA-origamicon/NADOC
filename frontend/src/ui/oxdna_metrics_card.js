import {umbrellaResultsButton} from './oxdna_umbrella_results.js'
/**
 * oxdna_metrics_card.js — the "Graphs and Metrics" card in the oxDNA Dynamics panel.
 *
 * A thin binding of the shared, engine-agnostic `initMetricsCard` factory (metrics_card.js)
 * to the oxDNA REST surface (`startOxdnaMetrics` / `getOxdnaMetricsRun`) and the
 * `oxdna-metrics-*` DOM ids.  All behaviour lives in metrics_card.js; the MD panel binds
 * the same factory to its own ids + endpoints (md_metrics_card.js).
 */

import { startOxdnaMetrics, getOxdnaMetricsRun, getOxdnaTorsionResults, lastErrorMessage } from '../api/client.js'
import { initMetricsCard, METRIC_META } from './metrics_card.js'
import { initTorqueMetrics } from './oxdna_torsion.js'

export function initOxdnaMetricsCard({ getSelectedJob = null, getJobs = null } = {}) {
  const card = document.getElementById('oxdna-metrics-card')
  const vmmc = document.createElement('div')
  card?.prepend(vmmc)
  const render = () => {const button=umbrellaResultsButton(getSelectedJob?.());vmmc.replaceChildren(...(button ? [button] : []))}
  window.addEventListener('nadoc:oxdna-job-selected',render)
  render()
  const torque = initTorqueMetrics({
    mount: document.getElementById('oxdna-metrics-torque'), getJob: getSelectedJob,
    result: id => getOxdnaTorsionResults(id), lastError: () => lastErrorMessage(),
  })
  window.addEventListener('nadoc:oxdna-job-selected', torque.refresh)
  const metrics = initMetricsCard({
    idPrefix: 'oxdna-metrics', selectionEvent: 'nadoc:oxdna-job-selected',
    api: { start: startOxdnaMetrics, poll: getOxdnaMetricsRun },
    extraMetrics: [{ key: 'oxdna_energy', tok: 'energy', request: { metric: 'oxdna_energy' } }],
    getSelectedJob, getJobs,
  })
  return {...metrics,refresh(){metrics.refresh();render();torque.refresh()}}
}

export { METRIC_META }
