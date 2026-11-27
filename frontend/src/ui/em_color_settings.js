import {normalizeEMColors} from '../scene/em_colors.js'
const key='nadoc.em.colors.v1'
let volatileColors=null
export function loadEMColors(){if(volatileColors)return {...volatileColors};try{return normalizeEMColors(JSON.parse(localStorage.getItem(key)||'{}'))}catch{return normalizeEMColors()}}
export function saveEMColors(value){
 const colors=normalizeEMColors(value)
 try{localStorage.setItem(key,JSON.stringify(colors));volatileColors=null}catch{volatileColors=colors}
 window.dispatchEvent(new CustomEvent('nadoc:em-colors',{detail:colors}))
 return colors
}
