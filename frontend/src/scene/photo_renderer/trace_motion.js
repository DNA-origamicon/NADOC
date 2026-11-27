// Resolution adaptation applies only to changing views. Completed stills and
// exports always use native resolution. No history is blended across cameras.
export function createTraceMotion({fps=15,minScale=.25}={}){
  const period=1000/fps
  let scale=.65,renderedScale=1,nextAt=0,started=null,pending=false,lastLatencyMs=null,updates=0
  return {
    begin(time){nextAt=time;started=null;pending=false},
    complete(time){
      if(!pending)return
      lastLatencyMs=time-started;pending=false
      if(lastLatencyMs>period*.95)scale=Math.max(minScale,scale*Math.sqrt(period*.8/lastLatencyMs))
      else if(lastLatencyMs<period*.8)scale=Math.min(1,scale*1.1)
    },
    due:time=>!pending&&time>=nextAt,
    submit(time,width,height){
      started=time;pending=true;updates++
      nextAt=Math.max(nextAt+period,time) // fixed cadence avoids 60 Hz → 12 FPS quantization
      const fit=scale;renderedScale=fit
      return {width:Math.max(1,Math.round(width*fit)),height:Math.max(1,Math.round(height*fit))}
    },
    get state(){return {targetFPS:fps,resolutionScale:renderedScale,nextResolutionScale:scale,viewLatencyMs:lastLatencyMs,viewUpdates:updates}},
  }
}
