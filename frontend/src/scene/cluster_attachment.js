/** Coalesce the two selection subscribers and reject superseded async attaches. */
export function createClusterAttachment(read) {
  let pending=null
  return (clusterId,task)=>{
    const start=read()
    if(pending?.clusterId===clusterId && pending.design===start.design && pending.epoch===start.epoch)return pending.promise
    const request={clusterId,design:start.design,epoch:start.epoch}
    pending=request
    const current=()=>{
      const state=read()
      return pending===request && state.active && state.design===request.design && state.epoch===request.epoch
    }
    request.promise=Promise.resolve().then(()=>task(current)).finally(()=>{if(pending===request)pending=null})
    return request.promise
  }
}
