/** Ordered SSE texture deltas. Each connection owns a cache; first state is full. */
export function encodeVRUIState(state, textures) {
  const ui=state.avatar?.pose?.ui
  if(!ui){textures.clear();return state}
  const next=new Map(),panels=ui.panels.map(panel=>{
    next.set(panel.id,panel.png)
    return textures.get(panel.id)===panel.png ? {id:panel.id,corners:panel.corners,reuse:true} : panel
  })
  textures.clear();for(const [id,png] of next)textures.set(id,png)
  return {...state,avatar:{...state.avatar,pose:{...state.avatar.pose,ui:{...ui,panels}}}}
}
export function decodeVRUIState(state,textures) {
  const ui=state?.avatar?.pose?.ui
  if(!ui){textures.clear();return state}
  if(!Array.isArray(ui.panels)||ui.panels.length>5)throw Error('Invalid VR menu stream')
  const next=new Map(),panels=ui.panels.map(panel=>{
    const png=panel.reuse===true?textures.get(panel.id):panel.png
    if(typeof png!=='string')throw Error('Missing VR menu texture')
    next.set(panel.id,png);return {id:panel.id,corners:panel.corners,png}
  })
  textures.clear();for(const [id,png] of next)textures.set(id,png)
  return {...state,avatar:{...state.avatar,pose:{...state.avatar.pose,ui:{...ui,panels}}}}
}
