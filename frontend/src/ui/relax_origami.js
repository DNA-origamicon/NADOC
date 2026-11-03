import { createModal } from './primitives/modal.js'

export function showRelaxOrigami({ api }) {
  const body = document.createElement('div')
  body.innerHTML = `<p>Minimize stretched backbone bonds between rigid clusters. Existing geometry clusters are used, or detected when absent. Each body retains its internal shape. Clash prevention currently supports planar layouts and keeps them flat. Strand connectivity stays unchanged.</p>
    <p>Short bonds retain their reference lengths; long bonds are pulled toward backbone contour length. Expanded helix-axis envelopes keep rigid bodies apart. This conservative clearance model can increase bond stretch; it does not check atomistic or internal-body clashes. No simulation engine is used. Apply is undoable.</p>
    <button type="button">Relax current design</button><p role="status" aria-live="polite"></p>`
  const button = body.querySelector('button')
  const status = body.querySelector('[role=status]')
  button.addEventListener('click', async () => {
    button.disabled = true
    status.textContent = 'Minimizing backbone stretch…'
    try {
      const report = await api.relaxOrigami()
      if (!report) throw new Error(api.lastErrorMessage?.() || 'Relaxation failed.')
      const clashes = report.clashes ? ` Overlapping body envelopes: ${report.clashes.before.overlapping_body_pairs} → ${report.clashes.after.overlapping_body_pairs}.` : ''
      status.textContent = `Maximum bond excess: ${report.before.max_excess_nm.toFixed(2)} → ${report.after.max_excess_nm.toFixed(2)} nm. ${report.after.stretched_bonds} inter-cluster bonds remain stretched. ${report.optimizer_converged ? 'Optimizer stopped at a local solution.' : 'Feasible partial fit applied; optimizer did not converge.'} Use Undo to restore the previous poses.${clashes}`
    } catch (error) {
      status.textContent = error.message
    } finally { button.disabled = false }
  })
  const modal = createModal({ title: 'Relax Origami', body, className: 'relax-origami-modal' })
  modal.open()
  return modal
}
