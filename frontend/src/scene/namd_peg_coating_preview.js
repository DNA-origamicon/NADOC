import * as THREE from 'three'

/** Saved graft-site markers only: no invented chain conformations or atom positions. */
export function initNamdPegCoatingPreview({scene}) {
  const group=new THREE.Group();group.name='NAMD PEG coating graft preview';scene.add(group)
  group.visible=false
  let record=null, visible=true, selected=null
  const clear=()=>{for(const node of [...group.children]){group.remove(node);node.geometry?.dispose();node.material?.dispose()}}
  function update(event){
    const coating=selected?.enabled ? selected.coating : null
    if(coating!==record){
      record=coating;clear()
      const points=coating?.preview?.graft_sites_nm || []
      if(points.length && points.every(p=>p.length===3 && p.every(Number.isFinite))){
        const geometry=new THREE.BufferGeometry()
        geometry.setAttribute('position',new THREE.Float32BufferAttribute(points.flat(),3))
        group.add(new THREE.Points(geometry,new THREE.PointsMaterial({color:'#61d9b4',size:.35,sizeAttenuation:true})))
      }
    }
    group.visible=!!coating && visible!==false
  }
  const onSelection=event=>{selected=event.detail;update()}
  const onVisibility=event=>{visible=event.detail?.visible!==false;update()}
  window.addEventListener('nadoc:namd-surface-selection',onSelection)
  window.addEventListener('nadoc:namd-peg-coating',onVisibility)
  return {dispose(){window.removeEventListener('nadoc:namd-peg-coating',onVisibility);window.removeEventListener('nadoc:namd-surface-selection',onSelection);clear();scene.remove(group)}}
}
