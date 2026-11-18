import {createInput,el} from './primitives/index.js'

/** Common salt control for fresh, continued and edited jobs. */
export function saltControl({value,onChange,inherit=false,thermal=false}) {
  const input=createInput({size:'sm',type:'number',min:0.000001,step:'any',value:value ?? ''})
  input.setAttribute('aria-label',thermal ? 'Thermal ramp salt concentration (M)' : 'Salt concentration (M)')
  input.dataset.oxdnaSalt=''
  input.dataset.oxdnaField='salt_concentration'
  input.addEventListener('input',()=>onChange(input.value==='' ? undefined : Number(input.value)))
  return el('label',{className:'wizard-field wizard-salt',children:[
    el('span',{className:'wizard-field__label',text:'Salt concentration (M)'}),input,
    el('span',{className:'wizard-field__help',text:inherit
      ? 'All stages. Blank uses the continued job’s salt.' : 'Monovalent salt concentration for all stages.'}),
  ]})
}

export function recordedStageConditions(job) {
  const specs=job.stage_specs || []
  return el('div',{className:'oxdna-thermal-recorded__table',children:[el('table',{children:[
    el('thead',{children:[el('tr',{children:['Stage','Temperature','Salt (M)','Steps'].map(text=>el('th',{text}))})]}),
    el('tbody',{children:(job.stages || []).map(stage=>{
      const spec=specs.find(s=>s.name===stage.name) || {}
      return el('tr',{children:[stage.name,spec.temperature ?? stage.temperature,
        spec.salt_concentration ?? job.salt_concentration,spec.steps ?? stage.steps].map(v=>el('td',{
        text:v==null?'Not recorded':typeof v==='number'?v.toLocaleString(undefined,{maximumFractionDigits:8}):String(v),
      }))})
    })}),
  ]})]})
}

export function recordedOptions(config, prefix = '', depth = 0) {
  return Object.entries(config || {}).flatMap(([key,value]) => {
    if (['stages','stage_overrides','thermal_progress','inherited_parameters'].includes(key)) return []
    const label = `${prefix}${key.replaceAll('_',' ')}`
    if (Array.isArray(value)) return [[label, value.length <= 4 && value.every(v=>typeof v!=='object')
      ? value.join(', ') : `${value.length} entries — see Full configuration`]]
    if (value && typeof value === 'object') return depth < 2 ? recordedOptions(value,`${label} / `,depth+1)
      : [[label,'See Full configuration']]
    return [[label,value]]
  })
}
