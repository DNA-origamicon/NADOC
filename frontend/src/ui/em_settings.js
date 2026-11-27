import {loadEMColors} from './em_color_settings.js'
/** Shared persisted optical and display options; no molecular/document mutations. */
export const EM_DEFAULTS = Object.freeze({ solver:'multipole', wavelength:520, shell:'ssdna_wlc', 'oligo-length':20,
  persistence:2.5, thickness:2.5, 'shell-index':1.7, polarization:'parallel', sampling:'field_adaptive',
  resolution:33, mode:'volume', 'dot-size':3, lighting:'glow', slice:.5, minimum:3 })
const choices = { solver:['multipole','multipole_reference'], shell:['none','manual','ssdna_wlc'],
  polarization:['parallel','perpendicular'], sampling:['uniform','adaptive','field_adaptive'],
  resolution:[25,33,49], mode:['volume','smooth','xy','xz','yz'], lighting:['off','glow','illuminate'] }
const bounds = { wavelength:[187.9,1937], 'oligo-length':[1,200], persistence:[.1,10], thickness:[0,100], 'shell-index':[1,2.5],
  'dot-size':[1,12], slice:[0,1], minimum:[0,1000] }
const key = 'nadoc.em.settings.v1'
export function sanitizeEMSettings(input = {}) {
  return Object.fromEntries(Object.entries(EM_DEFAULTS).map(([name, fallback]) => {
    let value = typeof fallback === 'number' ? Number(input[name] ?? fallback) : input[name] ?? fallback
    if ((choices[name] && !choices[name].includes(value)) || (bounds[name] && (!Number.isFinite(value) || value < bounds[name][0] || value > bounds[name][1])) || (name === 'oligo-length' && !Number.isInteger(value))) value = fallback
    return [name, value]
  }))
}
export function loadEMSettings() {
  try { return sanitizeEMSettings(JSON.parse(localStorage.getItem(key) || '{}')) } catch { return { ...EM_DEFAULTS } }
}
export function saveEMSettings(settings) {
  const value = sanitizeEMSettings(settings)
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* session listeners still receive settings */ }
  window.dispatchEvent(new CustomEvent('nadoc:em-settings', { detail:value }))
  return value
}
export function opticalSettings(s) {
  return { wavelength_nm:Number(s.wavelength ?? 520), solver:s.solver, resolution:Number(s.resolution), sampling:s.sampling, polarization:s.polarization,
    shell:{ model:s.shell, ...(s.shell==='none'?{}:{refractive_index:Number(s['shell-index']),
      ...(s.shell==='manual'?{thickness_nm:Number(s.thickness)}:{oligo_length_nt:Number(s['oligo-length']), persistence_length_nm:Number(s.persistence)})}) } }
}
export function displaySettings(s) { return { mode:s.mode, slice:s.slice, minimum:s.minimum, ...loadEMColors(), dotSize:s['dot-size'], lighting:s.lighting } }
