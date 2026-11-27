import {el} from './primitives/index.js'
import {vmmcDiagnostics} from './oxdna_vmmc_diagnostics.js'

export const VMMC_DEFAULTS = Object.freeze({temperature_c:70,start_c:60,end_c:80,step_c:2,
  tuning_rounds:4,tuning_steps:200000,equil_steps:200000,production_steps:2000000000,replicas:5})
const labels = {temperature_c:'Sampling temperature (°C)',start_c:'Analysis start (°C)',end_c:'Analysis end (°C)',step_c:'Analysis increment (°C)',
 tuning_rounds:'Weight-tuning rounds',tuning_steps:'MC steps per tuning round',equil_steps:'Equilibration steps per replica',production_steps:'Production steps per replica',replicas:'Independent replicas'}
export const vmmcConfig = config => Object.fromEntries(Object.entries(VMMC_DEFAULTS).map(([k,v])=>[k,config?.[k] ?? v]))
export function vmmcError(config) {
 if (!config) return null
 const c=vmmcConfig(config)
 if(Object.values(c).some(v=>!Number.isFinite(v))) return 'VMMC settings must be finite numbers.'
 if(c.start_c<=0||c.end_c>150||c.end_c<=c.start_c||c.step_c<=0||c.step_c>20||Math.ceil((c.end_c-c.start_c)/c.step_c)>40) return 'Choose an increasing 0–150°C analysis range with at most 41 points.'
 if(c.temperature_c<c.start_c||c.temperature_c>c.end_c) return 'Sampling temperature must be inside the analysis range.'
 for(const [key,min,max] of [['replicas',3,20],['tuning_rounds',1,20],['tuning_steps',1000,1e8],['equil_steps',1000,1e8],['production_steps',1000,1e10]])
  if(!Number.isInteger(c[key])||c[key]<min||c[key]>max) return `${labels[key]} must be an integer from ${min.toLocaleString()} to ${max.toLocaleString()}.`
 return null
}
export function vmmcStages(config, salt=.3) {
 const c=vmmcConfig(config),stages=[]
 const add=(role,index,steps,purpose)=>stages.push({name:`${stages.length+1}_vmmc_${role}_${index+1}`,purpose,steps,sim_type:'VMMC',backend:'CPU',temperature:`${c.temperature_c+273.15}K`,salt_concentration:salt,print_conf_interval:Math.max(1,Math.min(1000000,Math.floor(steps/100)))})
 for(let i=0;i<Math.min(20,Math.max(1,c.tuning_rounds||1));i++) add('tune',i,c.tuning_steps,`Tune weights · round ${i+1}`)
 for(let i=0;i<Math.min(20,Math.max(1,c.replicas||1));i++){add('equil',i,c.equil_steps,`Equilibrate replica ${i+1}`);add('sample',i,c.production_steps,`Sample replica ${i+1} · frozen weights`)}
 return stages
}
export function vmmcControls(config,onChange,{salt,dna}={}) {
 const root=el('fieldset',{className:'oxdna-thermal oxdna-vmmc',children:[el('legend',{text:'Equilibrium melting'})]})
 const toggle=el('input',{className:'checkbox',attrs:{type:'checkbox','data-vmmc-field':'enabled'}})
 toggle.checked=!!config;toggle.addEventListener('change',()=>onChange(toggle.checked?{...VMMC_DEFAULTS}:null))
 root.append(el('label',{className:'oxdna-thermal__toggle',children:[toggle,el('span',{text:'Enable CPU VMMC umbrella sampling'})]}))
 if(!config) return root
 const c=vmmcConfig(config),grid=el('div',{className:'oxdna-thermal__grid'})
 root.append(el('p',{className:'wizard-note',text:'For an undamaged complementary duplex continued from a prepared/relaxed job. CPU only. Weight tuning and equilibration are excluded from the melting estimate. This mode replaces the thermal ramp.'}),grid)
 for(const [key,label] of Object.entries(labels)) {
  const input=el('input',{className:'input input--sm',attrs:{type:'number',step:key.endsWith('_c')?'any':'1',value:c[key],'data-vmmc-field':key,'aria-label':label}})
  input.addEventListener('change',()=>onChange({...c,[key]:Number(input.value)}))
  grid.append(el('label',{className:'wizard-field',children:[el('span',{text:label}),input]}))
  if(key==='temperature_c'&&salt) grid.append(salt)
 }
 if(dna) root.append(dna)
 root.append(el('p',{className:'wizard-note',text:'Guide-based production: 2 billion MC steps per replica; trajectory every 1 million steps, energy every 100,000 steps (short runs use finer output). The guide demonstrates an RNA 8-mer, not universal DNA temperatures or weights. Tune weights for your sequence and concentration; the four short tuning rounds are a starting budget, not a convergence guarantee.'}))
 root.append(el('p',{className:'oxdna-thermal__help',text:'The analysis range uses histogram reweighting, not temperature ramps. Production weights are frozen. Sparse transitions or an unbracketed melting curve produce an inconclusive result. Interrupted stages restart from their stage seed; completed stages are retained.'}))
 return root
}
function download(name,text,type) {
 const url=URL.createObjectURL(new Blob([text],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),0)
}
export function vmmcResultView(job) {
 const root=el('div',{className:'oxdna-vmmc-results'}),result=job.run_config?.vmmc_result
 root.append(el('h3',{text:'VMMC equilibrium melting'}))
 if(!result){root.append(el('p',{text:'Results will appear after all production replicas finish. Tuning and equilibration are excluded.'}));return root}
 const tm=result.tm_c==null?'Tm unavailable':`${result.tm_c.toFixed(2)} °C`
 root.append(el('p',{className:'wizard-note',text:`${result.status==='inconclusive'?'Inconclusive — provisional: ':'Sampling checks passed: '}${tm}${result.replica_tm_sem_c==null?'':` · replica SEM ${result.replica_tm_sem_c.toFixed(2)} °C`}`}))
 for(const reason of result.reasons||[]) root.append(el('p',{text:reason}))
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 420 225');svg.setAttribute('role','img');svg.setAttribute('aria-label','Finite-size-corrected duplex fraction versus temperature');svg.style.width='100%';svg.style.maxWidth='650px'
 const ns=(tag,attrs,text)=>{const node=document.createElementNS(svg.namespaceURI,tag);for(const[k,v]of Object.entries(attrs))node.setAttribute(k,v);if(text)node.textContent=text;svg.append(node);return node}
 const ts=result.temperatures_c,lo=ts[0],hi=ts.at(-1),x=t=>45+(t-lo)/(hi-lo)*350,y=f=>185-155*f
 ns('line',{x1:45,y1:185,x2:395,y2:185,stroke:'currentColor'});ns('line',{x1:45,y1:30,x2:45,y2:185,stroke:'currentColor'})
 ns('line',{x1:45,y1:y(.5),x2:395,y2:y(.5),stroke:'#888','stroke-dasharray':'4 4'})
 for(const replica of result.replicas||[]) if(replica.yields?.length===ts.length) ns('polyline',{points:ts.map((t,i)=>`${x(t)},${y(replica.yields[i])}`).join(' '),fill:'none',stroke:'#a78bfa','stroke-width':1,opacity:.6})
 ns('polyline',{points:ts.map((t,i)=>`${x(t)},${y(result.duplex_yield[i])}`).join(' '),fill:'none',stroke:'#58a6ff','stroke-width':2})
 for(const f of [0,.5,1])ns('text',{x:16,y:y(f)+4,fill:'currentColor','font-size':12},String(f))
 for(const t of [lo,hi])ns('text',{x:x(t),y:203,'text-anchor':'middle',fill:'currentColor','font-size':12},`${t}°C`)
 ns('text',{x:210,y:220,'text-anchor':'middle',fill:'currentColor','font-size':12},'Temperature');ns('text',{x:50,y:18,fill:'currentColor','font-size':12},'Equilibrium duplex fraction')
 root.append(svg,el('p',{text:'Blue: mean corrected yield. Purple: individual replicas. Inconclusive curves are provisional and must not be interpreted as equilibrium melting estimates.'}))
 root.append(vmmcDiagnostics(result))
 root.append(el('p',{text:'Replica variation is a sampling diagnostic, not proof of convergence. Monte Carlo steps are not physical elapsed time.'}))
 const replicas=result.replicas||[]
 const csv=[['temperature_C','duplex_yield',...replicas.map((_,i)=>`replica_${i+1}_yield`)].join(','),...ts.map((t,i)=>[t,result.duplex_yield[i],...replicas.map(r=>r.yields?.[i]??'')].join(','))].join('\n')
 for(const [label,name,text,type]of [['Export melting CSV',`vmmc-${job.job_id}.csv`,csv,'text/csv'],['Export analysis JSON',`vmmc-${job.job_id}.json`,JSON.stringify(result,null,2),'application/json']]) {
  const button=el('button',{className:'btn btn--sm',text:label});button.addEventListener('click',()=>download(name,text,type));root.append(button)
 }
 return root
}
export function vmmcRecorded(job) {
 const cfg=job.run_config.vmmc_melting
 return el('div',{className:'oxdna-vmmc-recorded',children:[el('h3',{text:'CPU VMMC protocol'}),el('dl',{className:'oxdna-recorded-fields',children:Object.entries(labels).map(([key,label])=>el('div',{children:[el('dt',{text:label}),el('dd',{text:String(cfg[key])})]}))}),
  el('p',{text:`Salt: ${job.salt_concentration} M · Total DNA: ${job.run_config.box_conditions?.concentration_uM?.toPrecision(5) ?? 'not recorded'} µM`}),
  el('table',{children:[el('thead',{children:[el('tr',{children:['Stage','Status','MC steps'].map(text=>el('th',{text}))})]}),el('tbody',{children:job.stages.map(s=>el('tr',{children:[s.name,s.status,s.steps.toLocaleString()].map(text=>el('td',{text}))}))})]}),vmmcResultView(job)]})
}
