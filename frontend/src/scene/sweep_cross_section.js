import * as THREE from 'three'

/** One reusable planar footprint: outer envelope and visible helix rings. */
export function sweepSectionHull(cells, radius = 1) {
  const samples = cells.flatMap(([x,y]) => Array.from({length:8}, (_,i) => {
    const a=i*Math.PI/4; return [x+radius*Math.cos(a),y+radius*Math.sin(a)]
  })).sort((a,b)=>a[0]-b[0] || a[1]-b[1])
  if (samples.length < 3) return samples
  const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
  const half=values=>{ const out=[]; for(const p of values) { while(out.length>1 && cross(out.at(-2),out.at(-1),p)<=0) out.pop(); out.push(p) } return out }
  return [...half(samples).slice(0,-1),...half([...samples].reverse()).slice(0,-1)]
}

export function sweepSectionGeometry(cells, stride = 1) {
  const vertices=[]
  const hull=sweepSectionHull(cells)
  for(let i=0;i<hull.length;i++) vertices.push(...hull[i],0,...hull[(i+1)%hull.length],0)
  for(let i=0;i<cells.length;i+=stride) {
    const [x,y]=cells[i]
    for(let j=0;j<16;j++) {
      const a=j*Math.PI/8,b=(j+1)*Math.PI/8
      vertices.push(x+Math.cos(a),y+Math.sin(a),0,x+Math.cos(b),y+Math.sin(b),0)
    }
  }
  return new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(vertices,3))
}
