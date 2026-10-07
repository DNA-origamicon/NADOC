/** Standalone synthetic nucleotide construction has been removed. */
import { initStrandAnimApp } from './app.js'

try {
  initStrandAnimApp()
} catch (error) {
  const canvas = document.getElementById('strand-canvas')
  if (canvas) canvas.hidden = true
  const panel = document.getElementById('strand-panel-body')
  if (panel) { panel.textContent = error.message; panel.setAttribute('role', 'alert') }
  const readout = document.getElementById('strand-readout')
  if (readout) readout.textContent = 'Molecular preview unavailable'
}
