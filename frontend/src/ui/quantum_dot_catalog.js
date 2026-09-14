import catalog from '../../../backend/data/quantum_dots/catalog.json'

// The small offline catalog is part of the app, not another API request competing
// with startup job polling. Inline the original plots so the first preview also
// works while all browser HTTP connections are occupied by status requests.
const plots = import.meta.glob('../../../backend/data/quantum_dots/*.png', {
  eager: true, query: '?inline', import: 'default',
})

export function bundledQuantumDotCatalog() {
  return structuredClone(catalog)
}

export function quantumDotPlotUrl(entry) {
  return plots[`../../../backend/data/quantum_dots/${entry.spectra.plot_file}`]
    ?? `/api/nanoparticles/quantum-dots/catalog/${encodeURIComponent(entry.catalog_id)}/spectra`
}
