/** SNUPI host adapter for the shared bounded FEM metrics card. */
import { initCandoMetricsCard } from './cando_metrics_card.js'
import { getSnupiRmsf, getSnupiDeviation, getSnupiVisualizationBin } from '../api/client.js'
export function initSnupiMetricsCard(options = {}) {
  return initCandoMetricsCard({ ...options, prefix: 'snupi', label: 'SNUPI',
    fetchRmsf: getSnupiRmsf, fetchDeviation: getSnupiDeviation,
    fetchCompact: getSnupiVisualizationBin })
}
