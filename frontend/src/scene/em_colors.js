/** One intensity-to-color transfer for points, contours and the viewport legend. */
import {colormapRGB,normalizeColormap} from '../ui/colormaps.js'
export const EM_COLOR_DEFAULTS=Object.freeze({colorMinimum:.1,maximum:100,colormap:'jet'})
export function normalizeEMColors(value={}){
 const inputLow=Number(value.colorMinimum),inputHigh=Number(value.maximum)
 const colorMinimum=Number.isFinite(inputLow)&&inputLow>=1e-6&&inputLow<=1e12?inputLow:.1
 return {colorMinimum, maximum:Number.isFinite(inputHigh)&&inputHigh>colorMinimum&&inputHigh<=1e15?inputHigh:Math.max(100,colorMinimum*10),
  colormap:value.colormap?normalizeColormap(value.colormap):'jet'}
}
export function emColorFraction(value,{colorMinimum=.1,maximum=100}={}){
 return Math.max(0,Math.min(1,Math.log10(Math.max(value,1e-30)/colorMinimum)/Math.log10(maximum/colorMinimum)))
}
export function emColorRGB(value,options={}){return colormapRGB(options.colormap??'jet',emColorFraction(value,options))}
