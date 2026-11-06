import { heatmapHex } from './color_util.js'

export const UNKNOWN_TEMPERATURE_COLOR = 0x808080
export const DEFAULT_TEMPERATURE_BOUNDS = Object.freeze({ lo: 20, hi: 90 })
export function temperatureColor(value, bounds = DEFAULT_TEMPERATURE_BOUNDS) {
  const { lo, hi } = bounds && Number.isFinite(bounds.lo) && Number.isFinite(bounds.hi) && bounds.hi > bounds.lo ? bounds : DEFAULT_TEMPERATURE_BOUNDS
  return value == null || !Number.isFinite(value) ? UNKNOWN_TEMPERATURE_COLOR
    : heatmapHex(14 + 46 * (value - lo) / (hi - lo))
}
