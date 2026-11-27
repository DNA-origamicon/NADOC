import {it,expect} from 'vitest'
import {compareTraceImages,estimateTraceNoise,createTraceMetrics} from './trace_metrics.js'
const pixels=x=>new Float32Array([x,x,x,1,x,x,x,1])
it('reports reference error in a fixed color domain and rejects nonfinite data',()=>{
  expect(compareTraceImages(pixels(1),pixels(1),{width:2})).toMatchObject({rmse:0,psnr:Infinity,ssim:1,invalidPixels:0})
  expect(compareTraceImages(pixels(.5),pixels(1),{width:2})).toMatchObject({rmse:.5,nrmse:.5})
  expect(compareTraceImages(pixels(.5),pixels(1)).psnr).toBeCloseTo(6.0206)
  expect(compareTraceImages(pixels(NaN),pixels(1)).invalidPixels).toBe(2)
})
it('estimates sample noise without treating spatial detail as noise',()=>{
  const image=new Float32Array([0,0,0,1,10,5,1,1])
  expect(estimateTraceNoise(image,image).relativeNoise).toBe(0)
  expect(estimateTraceNoise(pixels(1),pixels(2)).relativeNoise).toBe(.5)
})
it('separates display cadence from fresh samples and resets paired estimates on changes',()=>{
  let time=0;const m=createTraceMetrics({now:()=>time})
  m.frame();time=100;m.frame({samples:1,width:10,height:10,traced:true});time=200;m.frame({samples:1,traced:true})
  expect(m.get()).toMatchObject({displayFPS:10,tracedFPS:5,samplesPerSecond:5,totalCameraPaths:100,firstSampleMs:100})
  m.probe(1,pixels(1));m.probe(2,pixels(1));expect(m.get().relativeNoise).toBe(0)
  m.probe(5,pixels(2));expect(m.get().relativeNoise).toBeUndefined()
  m.reset();expect(m.get().probeSamples).toBe(0)
  time=3000;expect(m.get().displayFPS).toBe(0)
})

it('credits a fence that completes during a frame before a camera reset, without double counting',()=>{
  let time=0;const m=createTraceMetrics({now:()=>time})
  m.frame();time=100;m.frame({samples:0,traced:false})
  m.completeSamples({samples:1,width:10,height:10});m.completeSamples({samples:1,width:10,height:10})
  m.reset();expect(m.get()).toMatchObject({tracedFPS:10,totalCameraPaths:100})
})
