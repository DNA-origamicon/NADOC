/** Offline evidence entry. No API, document store, save, export or simulation. */
import { initMolecularPlacementAudit } from '../frontend/src/ui/molecular_placement_audit.js'

const bundle = window.MOTION_AUDIT
if (!['nadoc.member-motion-ordering-audit.v1', 'nadoc.member-motion-tail-audit.v1'].includes(bundle?.schema) || bundle.read_only !== true)
  throw new Error('Expected isolated member-motion evidence')
bundle.provider.panel_labels = { current: 'Current: appended owner', candidate: 'Candidate: world motion',
  ...bundle.provider.panel_labels }
bundle.provider.panel_notes = {
  current: 'Existing native owner ordering',
  candidate: 'Detached M(native prefix) — not authorized',
  defects: 'Exact detector bonds, rings and clashing atom pairs',
  ...bundle.provider.panel_notes,
}
const table = document.createElement('table')
const header = table.insertRow()
for (const label of ['Bond atom serials', 'Residues', 'Current nm', 'Candidate nm', 'Δ nm', 'Endpoint displacement nm', 'Local clashes', 'Local piercings']) {
  const th = document.createElement('th'); th.textContent = label; header.append(th)
}
for (const row of bundle.junctions) {
  const tr = table.insertRow()
  for (const value of [row.serials.join(' ↔ '), row.residues.map(r => r.join(':')).join(' ↔ '),
    row.current_length_nm.toFixed(6), row.candidate_length_nm.toFixed(6),
    row.length_delta_nm.toFixed(6), row.endpoint_displacement_nm.map(v => v.toFixed(6)).join(', '),
    `${row.current_defects.clashes.length} → ${row.candidate_defects.clashes.length}`,
    `${row.current_defects.piercings.length} → ${row.candidate_defects.piercings.length}`])
    tr.insertCell().textContent = value
}
document.getElementById('junctions').append(table)
if (bundle.full_displacement) {
  const full = document.createElement('pre')
  full.textContent = 'Full bead displacement (separate from atomistic junction measurements):\n'
    + JSON.stringify(bundle.full_displacement, null, 2)
  document.getElementById('junctions').append(full)
}
if (bundle.event_trace?.length) {
  const trace = document.createElement('pre')
  trace.textContent = JSON.stringify(bundle.event_trace, null, 2)
  const details = document.createElement('details'), summary = document.createElement('summary')
  summary.textContent = 'Compiled event and material trace'
  details.append(summary, trace)
  document.getElementById('junctions').append(details)
}
const audit = initMolecularPlacementAudit({ fetchAudit: async () => bundle })
document.getElementById('open-audit').addEventListener('click', () => audit.show())
window.addEventListener('pagehide', () => audit.dispose(), { once: true })
audit.show().then(() => { window.MOTION_AUDIT_READY = true })
