// Lossless runs of identical RGBA pixels: [count:uint32, rgba:4 bytes].
// Flat tablet fills dominate the image. A direct scan avoids codec startup and
// browser scheduling overhead while preserving every text/antialiasing pixel.
export function compressVRPanel(view) {
  if (![8,9].includes(view.schema)) return view
  const state=view.atlasState,key=state?.panelKey
  let packed=state?.compressedPanel
  if(!packed || packed.key!==key) {
    const source=new Uint32Array(view.pixels.buffer,view.pixels.byteOffset,view.pixels.byteLength/4)
    const runs=new Uint32Array(source.length*2)
    let used=0
    for(let i=0;i<source.length;){
      const color=source[i],start=i++
      while(i<source.length && source[i]===color)i++
      runs[used++]=i-start;runs[used++]=color
    }
    const pixels=used*4<view.pixels.length ? new Uint8Array(runs.buffer,0,used*4).slice() : view.pixels
    packed={key,pixels}
    if(state)state.compressedPanel=packed
  }
  return packed.pixels.length<view.pixels.length ? {...view,schema:view.schema+2,pixels:packed.pixels} : view
}
