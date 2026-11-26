import {showOpProgress,updateOpProgress,hideOpProgress} from './op_progress.js'

/** Same NADOC popup as video exports; uncountable stages stay indeterminate. */
export async function exportPhotoImage(mode,width,height) {
  const controller=new AbortController()
  const token=showOpProgress('Exporting Image','Preparing image…',{indeterminate:true,onCancel:()=>controller.abort()})
  const report=info=>updateOpProgress(token,{label:info.label,fraction:info.fraction??null})
  try {
    await new Promise(resolve=>setTimeout(resolve,0))
    const blob=await mode.renderToBlob(width,height,{signal:controller.signal,onProgress:report})
    controller.signal.throwIfAborted()
    report({label:'Writing PNG file…'})
    if(blob){
      const url=URL.createObjectURL(blob)
      try{const a=document.createElement('a');a.href=url;a.download=`nadoc-figure-${width}x${height}.png`;a.click()}
      finally{URL.revokeObjectURL(url)}
    }
    report({label:'Done',fraction:1})
  }finally{hideOpProgress(token)}
}
