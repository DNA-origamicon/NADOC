import { createModal } from './primitives/modal.js'

export function chooseOrigamiImportOptions() {
  return new Promise(resolve => {
    const body = document.createElement('div')
    body.innerHTML = `<label><input type="checkbox" name="relax-origami"> Relax after import (experimental)</label>
      <p>Move detected rigid bodies to reduce stretched bonds while preventing clashes between their helix envelopes. Currently supports planar layouts. Clearance may increase bond stretch.</p>
      <p>If relaxation is unavailable, the design is imported with an explanation.</p>
      <button type="button">Import design</button>`
    const modal = createModal({ title: 'Origami import options', body,
      className: 'origami-import-options', onClose: () => resolve(null) })
    body.querySelector('button').addEventListener('click', () => {
      resolve({ relaxOrigami: body.querySelector('input').checked })
      modal.close()
    })
    modal.open()
  })
}

export function importRelaxationMessage(report) {
  if (!report || report.status !== 'applied') return null
  return `Relaxation applied to ${report.rigid_bundle_sizes.length} rigid bodies. Maximum bond excess: ${report.before.max_excess_nm.toFixed(2)} → ${report.after.max_excess_nm.toFixed(2)} nm. ${report.optimizer_converged ? 'Local fit converged.' : 'Partial fit; optimizer did not converge.'}`
}
