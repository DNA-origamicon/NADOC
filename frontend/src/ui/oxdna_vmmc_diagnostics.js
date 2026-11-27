/** Saved sampling evidence; older analyses remain readable without new fields. */
import {el} from './primitives/index.js'
const number = value => Number.isFinite(value) ? value.toLocaleString(undefined,{maximumFractionDigits:3}) : 'Not recorded'
function table(headers, rows) {
 const wrapper=el('div');wrapper.style.overflowX='auto'
 const cell=(tag,text)=>{const node=el(tag,{text:String(text)});node.style.cssText='padding:6px 10px;text-align:left;font-size:14px;white-space:normal';return node}
 wrapper.append(el('table',{children:[el('thead',{children:[el('tr',{children:headers.map(h=>cell('th',h))})]}),el('tbody',{children:rows.map(row=>el('tr',{children:row.map(v=>cell('td',v))}))})]}))
 return wrapper
}
export function vmmcDiagnostics(result) {
 const root=el('section'),replicas=result.replicas||[],box=result.box_conditions||{}
 root.append(el('h4',{text:'Conditions and sampling'}),el('p',{text:`Sampling temperature: ${number(result.sampling_temperature_c)} °C · Salt: ${number(result.salt_concentration_M)} M · Total DNA strands: ${number(box.concentration_uM)} µM`}))
 if(box.box_nm?.length===3)root.append(el('p',{text:`Periodic box: ${box.box_nm.map(number).join(' × ')} nm. For a two-strand duplex, each strand species has half the total strand concentration.`}))
 if(replicas.length) root.append(table(['Replica','Tm (°C)','Pair-count states visited','Recorded transitions','Recorded samples'],replicas.map((r,i)=>[i+1,r.tm_c==null?'Not bracketed':number(r.tm_c),number(r.visited_pair_counts),number(r.observed_bound_unbound_transitions),number(r.recorded_samples)])))
 root.append(el('p',{text:'Transitions count changes between paired and unpaired in the saved energy records; brief contacts between records are missed. Histogram counts are correlated visits, not independent samples.'}))
 for(const [i,r] of replicas.entries()) {
  if(!r.pair_counts) continue
  const detail=el('details',{children:[el('summary',{text:`Replica ${i+1} · base-pair sampling`})]})
  detail.style.fontSize='14px'
  detail.querySelector('summary').style.fontSize='14px'
  detail.append(table(['Native pairs','Histogram visits','Biased occupancy (%)','Unbiased box probability'],r.pair_counts.map((q,j)=>[q,number(r.biased_counts[j]),(100*r.biased_occupancy[j]).toPrecision(6),r.unbiased_probability[j].toPrecision(6)])))
  root.append(detail)
 }
 if(replicas.length&&!replicas.some(r=>r.pair_counts))root.append(el('p',{text:'This older saved analysis does not contain pair-count histograms. Existing replica diagnostics are shown above.'}))
 return root
}
