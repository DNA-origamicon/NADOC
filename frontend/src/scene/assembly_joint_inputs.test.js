import { describe, expect, it, vi } from 'vitest'
import { captureAssemblyJointInputs, sameAssemblyJointInputs, initAssemblyJointRebuildGate } from './assembly_joint_inputs.js'

function assembly() {
  return { id: 'assembly', joints: [], instances: [{ id: 'a', representation: 'full',
    source: { type: 'file', path: 'part.nadoc' }, geometrySourceKey: 'f:/part.nadoc:1:' }] }
}

describe('joint input snapshots', () => {
  it('ignores only live representation and retains saved configuration representations', () => {
    const a = assembly(), before = captureAssemblyJointInputs(a)
    a.instances[0].representation = 'beads'
    expect(sameAssemblyJointInputs(before, captureAssemblyJointInputs(a))).toBe(true)
    a.configurations = [{ instances: [{ id: 'a', representation: 'cylinders' }] }]
    expect(sameAssemblyJointInputs(before, captureAssemblyJointInputs(a))).toBe(false)
  })

  it('serializes a repeated inline Design once and detects mutations within it', () => {
    const a = assembly(), design = { clusters: [{ transform: { translation: [0, 0, 0] } }] }
    const toJSON = vi.fn(() => design.clusters)
    design.toJSON = toJSON
    a.instances = ['a', 'b'].map(id => ({ id, source: { type: 'inline', design }, representation: 'full' }))
    const before = captureAssemblyJointInputs(a)
    expect(toJSON).toHaveBeenCalledOnce()
    expect(before.reusable).toBe(true)
    design.clusters[0].transform.translation[0] = 5
    expect(sameAssemblyJointInputs(before, captureAssemblyJointInputs(a))).toBe(false)
  })

  it('requires a live version before reusing file-backed indicators', () => {
    const a = assembly(), gate = initAssemblyJointRebuildGate({ eventTarget: null })
    const first = gate.begin(a)
    expect(gate.begin(a)).toBeNull()
    expect(gate.isCurrent(first, a)).toBe(true)
    delete a.instances[0].geometrySourceKey
    const unversioned = gate.begin(a)
    expect(gate.begin(a)).not.toBeNull()
    expect(gate.isCurrent(unversioned, a)).toBe(false)
  })

  it('retires forced, invalidated and disposed work even when authored inputs agree', () => {
    const a = assembly(), gate = initAssemblyJointRebuildGate({ eventTarget: null })
    const first = gate.begin(a), forced = gate.begin(a, { force: true })
    expect(gate.isCurrent(first, a)).toBe(false)
    expect(gate.isCurrent(forced, a)).toBe(true)
    gate.invalidate()
    expect(gate.isCurrent(forced, a)).toBe(false)
    expect(gate.begin(a)).not.toBeNull()
    gate.dispose()
    expect(gate.begin(a, { force: true })).toBeNull()
  })

  it('compares the non-enumerable live version from a v2 response', () => {
    const a = assembly()
    Object.defineProperty(a.instances[0], 'geometrySourceKey', { value: 'f:/part.nadoc:1:', enumerable: false, configurable: true })
    const before = captureAssemblyJointInputs(a)
    Object.defineProperty(a.instances[0], 'geometrySourceKey', { value: 'f:/part.nadoc:2:', enumerable: false })
    expect(sameAssemblyJointInputs(before, captureAssemblyJointInputs(a))).toBe(false)
  })

  it('retires same-ID document work on reset and removes its listener on disposal', () => {
    const target = new EventTarget(), remove = vi.spyOn(target, 'removeEventListener')
    const a = assembly(), gate = initAssemblyJointRebuildGate({ eventTarget: target })
    const before = gate.begin(a)
    target.dispatchEvent(new Event('nadoc:document-reset'))
    expect(gate.isCurrent(before, a)).toBe(false)
    expect(gate.begin(a)).not.toBeNull()
    gate.dispose()
    expect(remove).toHaveBeenCalledWith('nadoc:document-reset', expect.any(Function))
  })
})
