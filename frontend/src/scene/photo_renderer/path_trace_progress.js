/** Fractions count actual completed tile samples, never elapsed-time guesses. */
export function traceSampleProgress(tile,tiles,samples,target) {
  const done=Math.max(0,Math.min(target,samples))
  return {stage:'tracing',fraction:(tile+done/target)/tiles,
    label:`Path tracing · tile ${tile+1}/${tiles} · ${Math.floor(done)}/${target} samples`,
    tile:tile+1,tiles,samples:done,target}
}

export function traceVideoProgress(info,frame,frames) {
  const fraction=['tracing','reused','denoise','composite'].includes(info.stage)?info.fraction??0:info.stage==='complete'?1:0
  return {done:frame+fraction,total:frames,detail:`Frame ${frame+1}/${frames} · ${info.label}`}
}
