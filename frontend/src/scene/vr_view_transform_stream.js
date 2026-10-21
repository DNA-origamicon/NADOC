// Absolute display transforms relative to an immutable full-snapshot layout.
// No numeric deltas, decomposition, quantization, or dependence on the last frame.
function identical(a,b) {
 if(a===b)return true
 if(a.length!==b.length)return false
 const x=new Uint32Array(a.buffer,a.byteOffset,a.length),y=new Uint32Array(b.buffer,b.byteOffset,b.length)
 for(let i=0;i<x.length;i++)if(x[i]!==y[i])return false
 return true
}
export function encodeTransformUpdate(view, base, baseVersion, version, sequence=0, onFallback) {
 const reject=reason=>{onFallback?.(reason);return null}
 if(!base || view.schema!==6 || view.flags!==base.flags || view.atlasState!==base.atlasState || !view.batches?.length || view.batches.length!==base.batches.length)return reject('layout_or_atlas')
 const packed=[]
 for(let batch=0;batch<view.batches.length;batch++) {
  const b=view.batches[batch], old=base.batches[batch], a=b.instances, prior=old.instances
  if(b.name!==old.name || !identical(b.vertices,old.vertices) || a.length!==prior.length)return reject('mesh_layout')
  const bits=new Uint32Array(a.buffer,a.byteOffset,a.length), oldBits=new Uint32Array(prior.buffer,prior.byteOffset,prior.length)
  let translation=true
  for(let i=0;i<a.length;i+=20) {
   if(bits[i+3] || bits[i+7] || bits[i+11] || bits[i+15]!==0x3f800000 || oldBits[i+3] || oldBits[i+7] || oldBits[i+11] || oldBits[i+15]!==0x3f800000)return reject('non_affine')
   for(let j=16;j<20;j++)if(bits[i+j]!==oldBits[i+j])return reject('instance_color')
   if(translation)for(let j=0;j<12;j++)if(j%4!==3 && bits[i+j]!==oldBits[i+j]){translation=false;break}
  }
  const columns=translation?3:12, values=new Float32Array(a.length/20*columns)
  let offset=0
  for(let i=0;i<a.length;i+=20)for(let j=translation?12:0;j<15;j++)if(j%4!==3)values[offset++]=a[i+j]
  packed.push(new Uint32Array([a.length/20,columns]),values)
 }
 const header=new Uint32Array([7,version,view.flags,view.triangles.length/12,view.lines.length/12,view.sprites.length/15,0,0,view.batches.length,sequence,baseVersion])
 return new Blob([new TextEncoder().encode('NADOCVT1'),header,view.triangles,view.lines,view.sprites,...packed])
}
