import { docHeaders } from '../shared/doc_id.js'
import { validateSweepPreview } from './sweep_preview_protocol.js'

export function initSweepPreviewPublisher({getRoom, available, publish, request=fetch, onError=()=>{}, now=Date.now,
  setInterval:repeat=setInterval, clearInterval:cancel=clearInterval}) {
  let busy=false, disposed=false, signature=null, context=null, renewed=0, geometryAfter=0, reported=false
  async function tick() {
    const room=getRoom()
    if(disposed || busy || !room || !available())return
    busy=true
    try {
      const response=await request('/api/vr/presenter-pose?preview=1',{headers:docHeaders(),signal:AbortSignal.timeout(2000)})
      if(!response.ok)throw Error('Sweep preview connection unavailable')
      const preview=validateSweepPreview((await response.json()).preview ?? null), encoded=JSON.stringify(preview)
      if(disposed || !available() || getRoom()?.id!==room.id || getRoom()?.revision!==room.revision)return
      const key=room.id+':'+room.revision, changed=key!==context || signature!==encoded
      // Target 64 KiB/s of geometry per guest, with latest-only coalescing.
      // Cancel and scene handoffs bypass this budget so stale overlays clear promptly.
      if(changed && preview && key===context && now()<geometryAfter)return
      if(!changed && (!preview || now()-renewed<1000))return
      await publish(room,{revision:room.revision,...(changed?{preview}:{keep:true})})
      if(changed && preview)geometryAfter=now()+Math.max(100,(encoded.length+200)*1000/65536)
      context=key;signature=encoded;renewed=now();reported=false
    } catch(error) { signature=null; if(!disposed&&!reported){reported=true;onError(error.message)} }
    finally {busy=false}
  }
  const timer=repeat(tick,100)
  return {tick,dispose(){disposed=true;cancel(timer)}}
}
