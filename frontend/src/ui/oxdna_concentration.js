import {createInput,el} from './primitives/index.js'

export function concentrationError(value) {
  return value == null || value === '' || (Number.isFinite(Number(value)) && Number(value)>0)
    ? null : 'DNA concentration must be a positive number (µM total strands).'
}
export function concentrationBoxNm(strands,value) {
  return strands>0 && value>0 && !concentrationError(value)
    ? Math.cbrt(strands*1e30/(6.02214076e23*value)) : null
}
export function concentrationControl({value,onChange,strands=null,recorded=null,inherit=false}) {
  const input=createInput({size:'sm',type:'number',min:0,step:'any',value:value ?? ''})
  input.setAttribute('aria-label','DNA concentration (µM total strands)')
  input.placeholder=inherit?'Inherit source box':'Automatic box'
  input.dataset.oxdnaField='dna_concentration_uM'
  const feedback=el('span',{className:'wizard-field__help',attrs:{'aria-live':'polite'}})
  const paint=()=>{
    const error=concentrationError(input.value), box=concentrationBoxNm(strands,input.value)
    input.setCustomValidity(error || '')
    feedback.textContent=error || (box ? `Box edge ≈ ${box.toFixed(2)} nm for ${strands} DNA strands; checked during preparation.`
      : recorded ? `Source: ${recorded.concentration_uM.toPrecision(4)} µM; box ${recorded.box_nm.map(n=>n.toFixed(2)).join(' × ')} nm.`
        : 'Box size is calculated from the exported DNA strand count during preparation.')
  }
  input.addEventListener('input',()=>{paint();onChange(input.value===''?null:Number(input.value))})
  paint()
  return el('label',{className:'wizard-field wizard-dna-concentration',children:[
    el('span',{className:'wizard-field__label',text:'DNA concentration (µM total strands)'}),input,
    el('span',{className:'wizard-field__help',text:'Sum of all DNA strands, not nucleotides or salt. For a duplex, 12,000 µM = 6 mM of each strand. Blank keeps the automatic/inherited box.'}),feedback,
  ]})
}
