import {namdPegFormSpec} from './namd_peg_surface_model.js'
/** Fixed-charge two-wall setup intent. No engine configuration is emitted yet. */
export const TWO_ELECTRODE_BARRIER = 'Two-electrode jobs are not ready: use Electrode relaxation in the wizard. Native qualification is in progress.'

export function twoElectrodeSpec({ axis, gap, width, depth, charge }) {
  const raw = [gap, width, depth, charge]
  const [gapNm, widthNm, depthNm, sigma] = raw.map(Number)
  if (raw.some(v => String(v).trim() === '') || raw.some(v => !Number.isFinite(Number(v)))) throw Error('Enter finite electrode dimensions and charge density.')
  if (!['x', 'y', 'z'].includes(axis)) throw Error('Choose an electrode normal.')
  if (gapNm < 2 || gapNm > 200 || widthNm < 2 || widthNm > 200 || depthNm < 2 || depthNm > 200) throw Error('Use electrode dimensions and gap between 2 and 200 nm.')
  if (Math.abs(sigma) > 0.5) throw Error('Use a charge density between −0.5 and +0.5 C/m².')
  return { schema: 'nadoc.two_electrodes.v1', model: 'abstract_fixed_charge', normal: axis,
    gap_nm: gapNm, width_nm: widthNm, depth_nm: depthNm,
    working_charge_C_m2: sigma, counter_charge_C_m2: -sigma }
}

export function initNamdTwoElectrodes({ root = document } = {}) {
  const enable = root.querySelector('#md-two-electrodes-enable')
  const host = root.querySelector('#md-two-electrodes-settings')
  if (!enable || !host) return { assertReady() {}, restore() {}, payload:()=>null, reset() {}, dispose() {} }
  const controls = Object.fromEntries(['axis', 'gap', 'width', 'depth', 'charge'].map(key => [key, host.querySelector(`#md-two-electrodes-${key}`)]))
  const status = host.querySelector('[role=status]'), counter = host.querySelector('#md-two-electrodes-counter')
  const read = () => twoElectrodeSpec(Object.fromEntries(Object.entries(controls).map(([k, el]) => [k, el.value])))
  function paint() {
    host.dataset.enabled = String(enable.checked)
    for (const el of Object.values(controls)) el.disabled = !enable.checked
    try {
      const spec = read()
      counter.textContent = `${spec.counter_charge_C_m2.toFixed(4)} C/m²`
      window.dispatchEvent(new CustomEvent('nadoc:two-electrode-setup', {detail:{enabled:enable.checked,spec}}))
      status.textContent = enable.checked ? 'Use Electrode relaxation in the wizard. Fixed cell; native qualification in progress.' : ''
    } catch (error) { window.dispatchEvent(new CustomEvent('nadoc:two-electrode-setup', {detail:{enabled:false}})); counter.textContent = '—'; status.textContent = enable.checked ? error.message : '' }
  }
  enable.addEventListener('change', paint)
  host.addEventListener('input', paint)
  host.addEventListener('change', paint)
  paint()
  return {
    assertReady() { if (enable.checked) read() },
    payload() { if(!enable.checked)return null;const value=read();if(root.querySelector('#md-peg-enable')?.checked)value.peg_coating={enabled:true,spec:namdPegFormSpec(root.querySelector('#namd-peg-surfaces form'))};return value },
    restore(spec) {enable.checked=!!spec;if(spec){for(const [key,field] of Object.entries({axis:"normal",gap:"gap_nm",width:"width_nm",depth:"depth_nm",charge:"working_charge_C_m2"}))controls[key].value=spec[field]}paint()},
    reset() { enable.checked = false; paint() },
    dispose() { window.dispatchEvent(new CustomEvent('nadoc:two-electrode-setup', {detail:{enabled:false}})); enable.removeEventListener('change', paint); host.removeEventListener('input', paint); host.removeEventListener('change', paint) },
  }
}
