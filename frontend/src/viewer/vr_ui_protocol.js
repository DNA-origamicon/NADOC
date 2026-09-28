/** Bounded, read-only XR drawing data. Panels carry PNG pixels, never URLs or actions. */
export const VR_PRESENCE_BYTES = 4 * 1024 * 1024
export function validateVRUI(value) {
  if (value == null) return undefined
  const fail=()=>{throw Error('Invalid VR presenter UI')}
  if (!value || !Array.isArray(value.lines) || value.lines.length>32768*6 || value.lines.length%12 ||
      !Array.isArray(value.panels) || value.panels.length>5) fail()
  const lines=value.lines.map((x,i)=>{
    if(!Number.isFinite(x) || (i%6<3 ? Math.abs(x)>1e5 : x<0||x>16))fail()
    return x
  })
  const ids=new Set();let bytes=0
  const panels=value.panels.map(p=>{
    if(!p || !['left-menu','right-menu','view-tools','tool-menu','desktop'].includes(p.id) || ids.has(p.id) ||
       !Array.isArray(p.corners) || p.corners.length!==12 || !p.corners.every(x=>Number.isFinite(x)&&Math.abs(x)<=1e5) ||
       typeof p.png!=='string' || (bytes+=p.png.length)>3*1024*1024 || p.png.length%4 || !/^[A-Za-z0-9+/]+={0,2}$/.test(p.png))fail()
    // Check PNG signature/IHDR and decoded dimensions before allocating browser images.
    const head=Uint8Array.from(atob(p.png.slice(0,44)),c=>c.charCodeAt(0)),d=new DataView(head.buffer)
    if(head.length<33 || d.getUint32(0)!==0x89504e47 || d.getUint32(4)!==0x0d0a1a0a || d.getUint32(8)!==13 || d.getUint32(12)!==0x49484452)fail()
    const w=d.getUint32(16),h=d.getUint32(20)
    if(!w||!h||w>8192||h>8192||w*h>16*1024*1024||head[24]!==8||head[25]!==6)fail()
    ids.add(p.id);return {id:p.id,corners:[...p.corners],png:p.png}
  })
  return {lines,panels}
}
