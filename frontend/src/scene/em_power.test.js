import {it,expect} from 'vitest'
import {emSamplePowers} from './em_lighting.js'
import {fieldSamples} from './em_field.js'

it('subdividing a cell preserves RGB illumination power',()=>{
  const coarse=emSamplePowers([8],[1,.5,.2],5)
  const fine=emSamplePowers(Array(8).fill(1),Array(8).fill([1,.5,.2]).flat(),5)
  for(let k=0;k<3;k++)expect(Array.from({length:8},(_,i)=>fine[i*3+k]).reduce((s,v)=>s+v,0)).toBeCloseTo(coarse[k],6)
  expect([...emSamplePowers([0],[1,1,1],5)]).toEqual([0,0,0])
})

it('keeps sample palettes while giving suppressed fields no illustrative surface power',()=>{
  const data={shape:[2,1,1],lower_nm:[0,0,0],upper_nm:[2,2,2],origin_nm:[0,0,0],basis:[[1,0,0],[0,1,0],[0,0,1]],intensity:[.2,100],outside:[true,true]}
  const samples=fieldSamples(data,{minimum:0})
  expect(samples.colors[2]).toBeGreaterThan(0)
  expect([...samples.powers.slice(0,3)]).toEqual([0,0,0])
  expect(samples.powers[3]).toBeGreaterThan(0)
})
