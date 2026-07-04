/**
 * oxdna_metrics_card.js — the "Graphs and Metrics" card in the oxDNA Dynamics panel.
 *
 * A thin binding of the shared, engine-agnostic `initMetricsCard` factory (metrics_card.js)
 * to the oxDNA REST surface (`startOxdnaMetrics` / `getOxdnaMetricsRun`) and the
 * `oxdna-metrics-*` DOM ids.  All behaviour lives in metrics_card.js; the MD panel binds
 * the same factory to its own ids + endpoints (md_metrics_card.js).
 */

import { startOxdnaMetrics, getOxdnaMetricsRun } from '../api/client.js'
import { initMetricsCard, METRIC_META } from './metrics_card.js'

export function initOxdnaMetricsCard({ getSelectedJob = null, getJobs = null } = {}) {
  return initMetricsCard({
    idPrefix: 'oxdna-metrics',
    api: { start: startOxdnaMetrics, poll: getOxdnaMetricsRun },
    getSelectedJob, getJobs,
  })
}

export { METRIC_META }
