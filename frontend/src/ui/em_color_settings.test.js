import {it,expect,vi,afterEach} from 'vitest'
import {loadEMColors,saveEMColors} from './em_color_settings.js'
afterEach(()=>{vi.restoreAllMocks();saveEMColors({});localStorage.clear()})
it('keeps color controls usable for this session when browser storage is unavailable',()=>{
 vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new Error('blocked')})
 saveEMColors({colorMinimum:1,maximum:250,colormap:'plasma'})
 expect(loadEMColors()).toEqual({colorMinimum:1,maximum:250,colormap:'plasma'})
})
it('loads persisted choices and recovers from invalid stored JSON',()=>{
 saveEMColors({colorMinimum:2,maximum:200,colormap:'magma'})
 expect(loadEMColors()).toEqual({colorMinimum:2,maximum:200,colormap:'magma'})
 localStorage.setItem('nadoc.em.colors.v1','{')
 expect(loadEMColors()).toEqual({colorMinimum:.1,maximum:100,colormap:'jet'})
})
