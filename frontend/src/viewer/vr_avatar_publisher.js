import { docHeaders } from '../shared/doc_id.js'
import { validateVRAvatar } from './vr_avatar_protocol.js'

/** One in-flight, latest-pose stream. Never creates a share or starts hosting. */
export function initVRAvatarPublisher({ getRoom, available, publish, request=fetch, onError=()=>{},
  setInterval: repeat=setInterval, clearInterval: cancel=clearInterval }) {
  let busy=false, disposed=false, sent=false, lastRoom=null, reported=false
  async function tick() {
    const room=getRoom()
    if(disposed || busy || !room || !available())return
    busy=true
    try {
      const response=await request('/api/vr/presenter-pose',{headers:docHeaders(),signal:AbortSignal.timeout(2000)})
      if(!response.ok)throw Error('VR tracking connection unavailable')
      const value=await response.json(),avatar=validateVRAvatar(value.avatar)
      if(disposed || getRoom()?.id!==room.id || getRoom()?.revision!==room.revision || !available())return
      if(!avatar && !sent && lastRoom===room.id)return
      await publish(room,{revision:room.revision,avatar})
      sent=!!avatar;lastRoom=room.id;reported=false
    } catch(error) { if(!disposed && !reported){reported=true;onError(error.message)} }
    finally {busy=false}
  }
  const timer=repeat(tick,100)
  return {tick,dispose(){disposed=true;cancel(timer)}}
}
