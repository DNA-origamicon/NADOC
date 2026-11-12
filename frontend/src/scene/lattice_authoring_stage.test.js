import { it, expect } from 'vitest'
import * as THREE from 'three'
import { createLatticeAuthoringStage } from './lattice_authoring_stage.js'

it('hides picking in length step without losing the footprint; restores original visibility', () => {
  const picker=new THREE.Group(), hidden=new THREE.Group(), preview=new THREE.Group(); hidden.visible=false
  const fill=new THREE.Mesh(); fill.position.set(2,3,4)
  const cells=[{fill}], selection=new Set(cells)
  const stage=createLatticeAuthoringStage({pickerNodes:[picker,hidden],preview,getCells:()=>cells,isSelected:c=>selection.has(c),getDirection:()=>new THREE.Vector3(0,0,-1),getLengthNm:()=>20})
  stage.set('section'); expect(preview.visible).toBe(false); expect(stage.canCommit()).toBe(false)
  stage.set('length'); expect(preview.visible).toBe(true); expect(picker.visible).toBe(false); expect(stage.canPick()).toBe(false)
  expect(stage.bounds(true).min.z).toBe(-17.5)
  expect(selection.size).toBe(1)
  stage.set('section'); expect(picker.visible).toBe(true); expect(hidden.visible).toBe(false)
  stage.set(null); expect(stage.canPick()).toBe(true); expect(preview.visible).toBe(true)
})
