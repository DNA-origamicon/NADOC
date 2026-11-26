/** Stream directly into the final image allocation; report actual received bytes. */
export async function readNativeImage(response,bytes,signal,onStatus){
  const report=done=>onStatus?.({stage:'delivery',fraction:done/bytes,label:`Receiving image · ${(done/1048576).toFixed(1)} / ${(bytes/1048576).toFixed(1)} MiB`})
  report(0)
  if(!response.body?.getReader){const result=await response.arrayBuffer();report(result.byteLength);return result}
  const data=new Uint8Array(bytes),reader=response.body.getReader()
  let offset=0
  try{
    for(;;){
      signal?.throwIfAborted()
      const {done,value}=await reader.read()
      if(done)break
      if(offset+value.byteLength>bytes)throw new Error('OptiX returned an oversized frame.')
      data.set(value,offset);offset+=value.byteLength;report(offset)
    }
    if(offset!==bytes)throw new Error('OptiX returned an incomplete frame.')
    return data.buffer
  }finally{await reader.cancel().catch(()=>{});reader.releaseLock()}
}
