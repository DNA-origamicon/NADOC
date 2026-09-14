import './namd_surface_charge.css'

/** Surface geometry/charge only. Salt and temperature belong to the job wizard. */
export const SCREENING_DEFAULTS = Object.freeze({ charge: -0.0413, padding: 3.65 })
export function screeningPayload({ enabled, charge, padding }) {
  if (!enabled) return {}
  const values=[charge,padding].map(Number)
  if ([charge,padding].some(v=>String(v).trim()==='') || values.some(v=>!Number.isFinite(v))) throw new Error('Enter finite surface parameters.')
  const [sigma,depth]=values
  if(Math.abs(sigma)>.5 || depth<2 || depth>30)throw new Error('Use |charge| ≤ 0.5 C/m² and reservoir depth 2–30 nm.')
  return {graphene_nanopore:true,graphene_only:true,graphene_charge_density_C_m2:sigma,
    graphene_pore_diameter_nm:0,graphene_layers:1,padding_nm:depth,field:null,skip_vacuum_prestage:true}
}
export function initNamdSurfaceCharge({ root = document } = {}) {
  const enable=root.querySelector('#md-screening-enable')
  if(!enable)return {payload:()=>({}),restore(){}}
  const charge=root.querySelector('#md-screening-charge'),padding=root.querySelector('#md-box-padding') || root.querySelector('#md-screening-padding'),status=root.querySelector('#md-screening-status')
  const read=()=>({enabled:enable.checked,charge:charge.value,padding:padding.value})
  function paint(){
    charge.disabled=!enable.checked
    if(padding.id==='md-screening-padding')padding.disabled=!enable.checked
    try {screeningPayload(read());status.textContent='';status.hidden=true}
    catch(error){status.textContent=error.message;status.hidden=false}
  }
  enable.addEventListener('change',paint)
  for(const input of [charge,padding])input.addEventListener('input',paint)
  paint()
  return {payload:()=>screeningPayload(read()),restore(p={}){
    enable.checked=Object.hasOwn(p,'graphene_charge_density_C_m2') && !!p.graphene_only && p.graphene_pore_diameter_nm===0
    charge.value=p.graphene_charge_density_C_m2 ?? SCREENING_DEFAULTS.charge
    if(padding.id==='md-screening-padding')padding.value=p.padding_nm ?? SCREENING_DEFAULTS.padding;paint()
  }}
}
