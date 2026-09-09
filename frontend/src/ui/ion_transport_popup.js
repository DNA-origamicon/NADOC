import { buildChartSpec, drawChart, SERIES_COLORS } from './metric_graph.js'

let root = null

function chronologicalRuns(time) {
  if (!time.length) return []
  const runs = [[0]]
  for (let i = 1; i < time.length; i += 1) {
    if (Number(time[i]) < Number(time[i - 1])) runs.push([])
    runs.at(-1).push(i)
  }
  return runs.sort((a, b) => Number(time[a[0]]) - Number(time[b[0]]))
}

function chronologicalPoints(time, values, { cumulative = false } = {}) {
  const runs = chronologicalRuns(time)
  if (!cumulative) return runs.flatMap(run => run.map(i => [time[i], values?.[i]]))
  let offset = 0
  return runs.flatMap(run => {
    const baseline = Number(values?.[run[0]]) || 0
    const points = run.map(i => [time[i], offset + (Number(values?.[i]) || 0) - baseline])
    if (points.length) offset = points.at(-1)[1]
    return points
  })
}

export function ionTransportSeries(result) {
  const time = result?.series?.time_ns || []
  const current = result?.series?.current_nA || {}
  const crossings = result?.series?.cumulative_crossings || {}
  const present = name => name === 'total'
    || result?.species?.[name]?.n_ions == null
    || Number(result.species[name].n_ions) > 0
  return {
    current: Object.entries(current).filter(([name]) => present(name)).map(([name, values], i) => ({
      label: name, color: SERIES_COLORS[i % SERIES_COLORS.length],
      points: chronologicalPoints(time, values),
    })),
    crossings: Object.entries(crossings).filter(([name]) => present(name)).map(([name, values], i) => ({
      label: `${name} net`, color: SERIES_COLORS[i % SERIES_COLORS.length],
      points: chronologicalPoints(time, values?.net || [], { cumulative: true }),
    })),
  }
}

export function openIonTransportPopup(result) {
  if (root) root.remove()
  root = document.createElement('div')
  root.style.cssText = 'position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;font-family:var(--font-ui,sans-serif)'
  root.innerHTML = `<div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:16px;max-width:95vw;max-height:92vh;overflow:auto;color:#c9d1d9">
    <div style="display:flex;justify-content:space-between;gap:16px;margin-bottom:8px"><strong>Nanopore ion transport</strong><button data-close style="background:#21262d;border:1px solid #30363d;border-radius:5px;color:#c9d1d9;padding:4px 10px;cursor:pointer">Close</button></div>
    <div data-summary style="font-size:12px;color:#8b949e;margin-bottom:10px"></div>
    <div style="display:flex;flex-wrap:wrap;gap:14px"><canvas data-current></canvas><canvas data-crossings></canvas></div>
    <div style="font-size:11px;color:#6e7681;margin-top:8px">Current uses charge displacement across the periodic cell. Crossings require the ion path to intersect the membrane plane inside the circular pore.</div>
  </div>`
  document.body.appendChild(root)
  const current = Number(result.mean_current_nA || 0)
  const conductance = result.conductance_nS == null ? '—' : `${Number(result.conductance_nS).toFixed(3)} nS`
  root.querySelector('[data-summary]').textContent = `${current.toFixed(4)} nA mean current · ${conductance} · ${result.frames || 0} frames · ${result.pore?.diameter_nm ?? '—'} nm pore`
  const series = ionTransportSeries(result)
  drawChart(root.querySelector('[data-current]'), buildChartSpec({ series: series.current, width: 560, height: 300, title: 'Electrical current', xLabel: 'simulation time (ns)', yLabel: 'current (nA)', zeroLine: true }))
  drawChart(root.querySelector('[data-crossings]'), buildChartSpec({ series: series.crossings, width: 560, height: 300, title: 'Aperture-validated crossings', xLabel: 'simulation time (ns)', yLabel: 'cumulative net crossings', zeroLine: true }))
  const close = () => { root?.remove(); root = null }
  root.querySelector('[data-close]').addEventListener('click', close)
  root.addEventListener('click', event => { if (event.target === root) close() })
}
