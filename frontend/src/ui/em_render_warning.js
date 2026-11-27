import {createModal} from './primitives/modal.js'
import {createButton} from './primitives/button.js'
import {hasEMRenderField,clearEMFields} from '../scene/em_export.js'

const pending = new WeakMap()

/** Ask before starting the costly combination; cancelling has no rendering effects. */
export function confirmEMRender({scene,mode,pathTracing=mode.getSettings().pathTracing}) {
  if(!pathTracing||!hasEMRenderField(scene))return 'continue'
  if(pending.has(scene))return pending.get(scene)
  const previous=document.activeElement
  const result=new Promise(resolve=>{
    let answered=false
    const finish=value=>{if(answered)return;answered=true;resolve(value)}
    const choose=value=>{
      if(value==='clear')clearEMFields(scene)
      if(value==='disable')mode.setPathTracing(false)
      finish(value);modal.close()
    }
    const modal=createModal({title:'EM field with GPU path tracing',size:'md',
      body:'Lighting and Appearance with GPU path tracing and an active EM field can make rendering take substantially longer. Continue with both, clear the EM field, or disable GPU path tracing?',
      actions:[['Continue','continue'],['Clear field','clear'],['Disable path tracing','disable'],['Cancel','cancel']].map(([label,value])=>createButton({label,onClick:()=>choose(value)})),
      onClose:()=>{finish('cancel');previous?.focus()}})
    modal.open()
    const buttons=[...modal.root.querySelectorAll('button')]
    buttons.at(-1)?.focus()
    modal.root.addEventListener('keydown',event=>{
      if(event.key!=='Tab')return
      const index=buttons.indexOf(document.activeElement)
      event.preventDefault();buttons[(index+(event.shiftKey?-1:1)+buttons.length)%buttons.length]?.focus()
    })
  })
  pending.set(scene,result);result.then(()=>pending.delete(scene))
  return result
}
