// Image metrics operate on linear RGB (RGBA input). PSNR/SSIM use an explicit
// peak, never a per-image rescale. Reference comparisons measure error; paired
// sample blocks estimate noise only and cannot detect bias or missing geometry.
export function compareTraceImages(actual,reference,{width,peak=1}={}) {
  if(actual.length!==reference.length || actual.length%4)throw new Error('Matching RGBA images required')
  const count=actual.length/4;let squared=0,signal=0,invalid=0
  const a=[],b=[]
  for(let i=0;i<actual.length;i+=4){
    if(![...actual.slice(i,i+4),...reference.slice(i,i+4)].every(Number.isFinite)){invalid++;continue}
    for(let k=0;k<3;k++){squared+=(actual[i+k]-reference[i+k])**2;signal+=reference[i+k]**2}
    a.push(.2126*actual[i]+.7152*actual[i+1]+.0722*actual[i+2]);b.push(.2126*reference[i]+.7152*reference[i+1]+.0722*reference[i+2])
  }
  if(invalid || !count)return {rmse:null,nrmse:null,psnr:null,ssim:null,invalidPixels:invalid}
  const mse=squared/(3*count),rmse=Math.sqrt(mse)
  let ssim=0,windows=0;const w=width??count,h=count/w
  if(!Number.isInteger(h))throw new Error('Invalid image width')
  for(let y=0;y<h;y+=8)for(let x=0;x<w;x+=8){
    let n=0,ma=0,mb=0,aa=0,bb=0,ab=0
    for(let dy=0;dy<8&&y+dy<h;dy++)for(let dx=0;dx<8&&x+dx<w;dx++){
      const i=(y+dy)*w+x+dx;n++;ma+=a[i];mb+=b[i];aa+=a[i]**2;bb+=b[i]**2;ab+=a[i]*b[i]
    }
    ma/=n;mb/=n
    const va=Math.max(0,aa/n-ma*ma),vb=Math.max(0,bb/n-mb*mb),cov=ab/n-ma*mb,c1=(.01*peak)**2,c2=(.03*peak)**2
    ssim+=((2*ma*mb+c1)*(2*cov+c2))/((ma*ma+mb*mb+c1)*(va+vb+c2));windows++
  }
  return {rmse,nrmse:signal?Math.sqrt(squared/signal):rmse===0?0:null,psnr:mse?10*Math.log10(peak*peak/mse):Infinity,ssim:ssim/windows,invalidPixels:0}
}

export function estimateTraceNoise(previous,current){
  // current=(A+B)/2 and previous=A, where A,B are independent equal-length
  // blocks. E[(current-previous)^2] is the variance of the current mean.
  const result=compareTraceImages(previous,current)
  return {relativeNoise:result.nrmse,noiseRMSE:result.rmse,invalidPixels:result.invalidPixels}
}
const percentile=(a,p)=>a.length?[...a].sort((x,y)=>x-y)[Math.min(a.length-1,Math.ceil(a.length*p)-1)]:null
export function createTraceMetrics({now=()=>performance.now()}={}){
  let started=now(),firstSampleMs=null,frames=[],last=null,lastSamples=0,paths=0,probe=null,noise=null,resets=0,readbackMs=0
  function reset(){started=now();firstSampleMs=null;lastSamples=0;probe=null;noise=null;resets++}
  function credit(frame,{samples=0,width=0,height=0,traced=true}={}){
    const completed=Math.max(0,Math.floor(samples)-Math.floor(lastSamples))
    const sampleDelta=Math.max(0,samples-lastSamples);lastSamples=samples
    const work=sampleDelta*width*height;paths+=work
    if(samples>=1&&firstSampleMs===null)firstSampleMs=now()-started
    frame.completed+=traced?completed:0;frame.samples+=sampleDelta;frame.paths+=work
  }
  return {
    // A fence can complete after the frame's first poll but before a new view
    // resets accumulation. Credit that completion once in the current frame.
    completeSamples(sample){if(frames.length)credit(frames.at(-1),sample)},
    reset,
    frame({samples=0,width=0,height=0,cpuMs=0,traced=false}={}){
      const time=now(),delta=last===null?null:time-last;last=time
      const frame={time,delta,cpuMs,completed:0,samples:0,paths:0}
      frames.push(frame);credit(frame,{samples,width,height,traced})
      frames=frames.filter(f=>time-f.time<=2000)
    },
    wantsProbe(samples){return Number.isInteger(samples)&&samples>=1&&(!probe||samples>=probe.samples*2)},
    probe(samples,pixels,ms=0){
      if(probe && samples===probe.samples*2)noise=estimateTraceNoise(probe.pixels,pixels)
      else noise=null
      probe={samples,pixels:pixels.slice()};readbackMs=ms
    },
    get(){
      const time=now(),recent=frames.filter(f=>time-f.time<=2000),intervals=recent.map(f=>f.delta).filter(v=>v>0),duration=intervals.reduce((a,b)=>a+b,0)/1000
      const sum=k=>recent.reduce((s,f)=>s+f[k],0)
      return {displayFPS:duration?intervals.length/duration:0,tracedFPS:duration?recent.filter(f=>f.completed>0).length/duration:0,tracedSamplesPerSecond:duration?sum('completed')/duration:0,
        samplesPerSecond:duration?sum('samples')/duration:0,millionPathsPerSecond:duration?sum('paths')/duration/1e6:0,
        frameP95Ms:percentile(intervals,.95),cpuP95Ms:percentile(recent.map(f=>f.cpuMs),.95),firstSampleMs,elapsedMs:time-started,
        totalCameraPaths:paths,resets,probeSamples:probe?.samples??0,probeReadbackMs:readbackMs,...noise}
    },
  }
}
