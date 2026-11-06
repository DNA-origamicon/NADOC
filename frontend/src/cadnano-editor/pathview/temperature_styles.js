import { estimateStapleTemperatures } from '../../scene/staple_temperature.js'
import { temperatureColor } from '../../scene/staple_temperature_colors.js'

/** Cached by immutable design identity, never recalculated for pan/zoom frames. */
export function createTemperatureStyles() {
  let design, estimates, mode = 'off', bounds
  const style = value => ({ color: '#' + temperatureColor(value, bounds).toString(16).padStart(6, '0'), thickMul: 1 })
  function domain(si, di) {
    if (mode === 'off') return null
    const result = estimates?.get(design?.strands?.[si]?.id)
    return result ? style(mode === 'total' ? result.total : result.domains[di]?.tm) : null
  }
  return {
    prepare(nextDesign, nextMode = 'off', nextBounds) {
      mode = nextMode; bounds = nextBounds
      if (mode !== 'off' && design !== nextDesign) { design = nextDesign; estimates = estimateStapleTemperatures(design) }
    },
    domain,
    strand: si => domain(si, -1), // Unpaired connectors/tails have no domain Tm.
    site(si, endpoint) {
      if (mode === 'off' || !estimates?.has(design?.strands?.[si]?.id)) return null
      if (mode === 'total') return domain(si, -1)
      const di = design?.strands?.[si]?.domains?.findIndex(d => d.helix_id === endpoint.helix_id
        && d.direction === endpoint.strand && endpoint.index >= Math.min(d.start_bp, d.end_bp)
        && endpoint.index <= Math.max(d.start_bp, d.end_bp))
      return domain(si, di)
    },
  }
}
