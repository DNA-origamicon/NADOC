import {expect,it,afterEach} from 'vitest'
import * as THREE from 'three'
import {initEMLegend} from './em_legend.js'
import {createEMFieldOverlay} from '../scene/em_field.js'
import {loadEMColors,saveEMColors} from './em_color_settings.js'
let legend,overlay
const data={shape:[2,2,2],intensity:Array(8).fill(10),outside:Array(8).fill(true),origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]],lower_nm:[0,0,0],upper_nm:[1,1,1]}
afterEach(()=>{overlay?.dispose();legend?.dispose();document.body.innerHTML='';localStorage.clear()})
it('shows only with a visible field, recolors independently of panels and remembers bounds',()=>{
 const scene=new THREE.Scene();legend=initEMLegend(scene);overlay=createEMFieldOverlay(scene)
 const root=document.getElementById('em-scale');expect(root.style.display).toBe('none')
 overlay.show(data,{mode:'volume'});expect(root.style.display).toBe('')
 const hi=root.querySelector('#em-scale-max');hi.value='1000';hi.dispatchEvent(new Event('change'))
 expect(loadEMColors().maximum).toBe(1000)
 root.querySelector('#em-scale-cmap').click();root.querySelector('[data-cmap="magma"]').click()
 expect(loadEMColors().colormap).toBe('magma')
 overlay.clear();expect(root.style.display).toBe('none')
 overlay.show(data,{mode:'xy'});expect(hi.value).toBe('1000.00')
 root.querySelector('#em-scale-reset').click();expect(loadEMColors().colorMinimum).toBe(.1)
})
it('external color changes update the legend without publishing a feedback loop',()=>{
 const scene=new THREE.Scene();legend=initEMLegend(scene)
 saveEMColors({colorMinimum:1,maximum:100,colormap:'viridis'})
 expect(document.querySelector('#em-scale-min').value).toBe('1.00')
 expect(document.querySelector('#em-scale-title').textContent).toContain('log')
 legend.dispose();legend=null
 expect(document.querySelector('#em-scale')).toBeNull()
})
