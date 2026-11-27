/** Viewport-owned legend; sidebar visibility never owns a calculated field. */
import {initFlexScale} from './flex_scale.js'
import {loadEMColors,saveEMColors} from './em_color_settings.js'
import './em_legend.css'
export function initEMLegend(scene){
 const flex=document.getElementById('flex-scale'),root=flex?flex.cloneNode(true):document.createElement('div')
 if(!flex)root.innerHTML='<div id="flex-scale-title"></div><input id="flex-scale-max" type="number"><div id="flex-scale-track"><div id="flex-scale-handle-hi"></div><div id="flex-scale-handle-lo"></div></div><input id="flex-scale-min" type="number"><button id="flex-scale-cmap" title="Colormap"></button><button id="flex-scale-reset">Reset</button>'
 root.querySelector('#flex-scale-help')?.remove();root.querySelector('#flex-scale-cmap-popup')?.remove()
 root.id='em-scale';root.setAttribute('aria-label','EM intensity color mapping');root.setAttribute('role','group')
 for(const el of root.querySelectorAll('[id]'))el.id=el.id.replace('flex-scale','em-scale')
 for(const bound of ['min','max']){
  const input=root.querySelector(`#em-scale-${bound}`);input.min='0.000001';input.step='any'
  input.setAttribute('aria-label',`${bound==='min'?'Lower':'Upper'} EM color bound`)
 }
 root.title='Intensity enhancement |E|² / |Eincident|² · logarithmic colors. Color bounds do not change the 3D cutoff.'
 ;(flex?.parentElement??document.getElementById('canvas-area')??document.body).append(root)
 root.querySelector('#em-scale-reset').title='Reset color bounds to 0.1–100×'
 const scale=initFlexScale({prefix:'em-scale',logarithmic:true,help:false,resetBounds:[.1,100]})
 let syncing=false
 const sync=()=>{
  syncing=true
  const value=loadEMColors()
  scale.show({title:'EM intensity × (log)',min:Math.min(.1,value.colorMinimum),max:Math.max(100,value.maximum),colormap:value.colormap,mapType:'em',
   onRecolor:(lo,hi,colormap)=>{if(!syncing)saveEMColors({colorMinimum:lo,maximum:hi,colormap})}})
  scale.setBounds(value.colorMinimum,value.maximum,{emit:false})
  syncing=false;visibility()
 }
 const visibility=()=>{
  const visible=scene.children?.some(o=>o.userData?.emField&&o.visible&&o.children?.some(c=>c.isPoints||c.isMesh||c.userData?.emField))
  if(visible)root.style.display='';else scale.hide()
  root.style.right=flex&&flex.style.display!=='none'?'92px':'14px'
 }
 const observer=flex?new MutationObserver(visibility):null
 observer?.observe(flex,{attributes:true,attributeFilter:['style']})
 scene.addEventListener?.('em-field-visibility',visibility)
 window.addEventListener('nadoc:em-colors',sync)
 sync()
 return {dispose(){observer?.disconnect();scene.removeEventListener?.('em-field-visibility',visibility);window.removeEventListener('nadoc:em-colors',sync);scale.dispose();root.remove()}}
}
