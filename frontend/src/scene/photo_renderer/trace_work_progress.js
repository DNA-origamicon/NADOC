const clamp=value=>Math.max(0,Math.min(1,value))

/** Weighted work, not an ETA. Unknown native/driver operations remain at their
 * last measured fraction until completion; never advance from elapsed time. */
export function createTraceWorkProgress(backend='webgl',target=64){
  const native=backend==='optix',quick=native&&target>1
  const definitions=native?[
    ['device','Renderer startup',5],['snapshot','Scene snapshot',10],['environment','Materials / environment',5],
    ['upload','Encode / transfer scene',10],['decode','Read / decode scene',3],['geometry','Native geometry / materials',17],
    ...(quick?[['quick-acceleration','First image: GPU setup',2.5],['quick-tracing','First image: sampling',25/(target+1)],
      ['quick-readback','First image: readback',2.5],['quick-delivery','First image: transfer',2.5]]:[]),
    ['acceleration','GPU setup / acceleration',quick?2.5:5],['tracing','Target image: sampling',quick?25*target/(target+1):25],
    ['readback','Image readback / output',quick?2.5:5],['delivery','Image transfer',quick?2.5:5],['display','Denoise / display',10],
  ]:[['snapshot','Scene snapshot',15],['geometry','Geometry / acceleration',20],['environment','Materials / environment',10],
    ['compile','GPU shader compilation',5],['tracing','Sampling',45],['display','Denoise / display',5]]
  const rows=definitions.map(([id,label,weight])=>({id,label,weight,fraction:0,state:'pending'}))
  let current=-1,detail='',complete=false
  function event(info){
    if(info.reused){for(const row of rows)if(info.reused.includes(row.id)){row.state='reused';row.fraction=1}return}
    const index=rows.findIndex(row=>row.id===info.stage)
    if(index<0||index<current||complete)return
    for(let i=0;i<index;i++)if(rows[i].state!=='reused'){rows[i].fraction=1;rows[i].state='complete'}
    current=index;detail=info.label??rows[index].label
    const row=rows[index]
    row.state='active';row.measured=Number.isFinite(info.fraction)
    if(row.measured)row.fraction=Math.max(row.fraction,clamp(info.fraction))
    if(row.fraction===1)row.state='complete'
    if(info.stage==='display'&&info.fraction===1)complete=true
  }
  return {event,get(){
    const work=rows.filter(row=>row.state!=='reused'),total=work.reduce((sum,row)=>sum+row.weight,0)
    const fraction=complete?1:Math.min(.999,work.reduce((sum,row)=>sum+row.weight*row.fraction,0)/total)
    return {fraction,complete,detail,indeterminate:current<0||rows[current].measured===false,
      stages:rows.map(row=>({...row,share:row.state==='reused'?0:row.weight/total}))}
  }}
}
