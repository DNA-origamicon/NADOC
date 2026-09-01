import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import * as THREE from 'three'
import {
  coalesceCylinderRuns, directConnectedOverhangIds, orderStrandNucleotides,
  rescaleInstanceInPlace, syncPatchedBeadPosition,
} from './helix_renderer.js'

describe('pose-preserving presentation edits', () => {
  it('changes instance scale without changing its live position or orientation', () => {
    const mesh = new THREE.InstancedMesh(
      new THREE.SphereGeometry(1), new THREE.MeshBasicMaterial(), 1,
    )
    const position = new THREE.Vector3(17, -4, 9)
    const quaternion = new THREE.Quaternion().setFromEuler(new THREE.Euler(.3, -.7, 1.1))
    mesh.setMatrixAt(0, new THREE.Matrix4().compose(
      position, quaternion, new THREE.Vector3(2, 2, 2),
    ))

    rescaleInstanceInPlace(mesh, 0, new THREE.Vector3(4, 5, 6))

    const matrix = new THREE.Matrix4()
    const actualPosition = new THREE.Vector3()
    const actualQuaternion = new THREE.Quaternion()
    const actualScale = new THREE.Vector3()
    mesh.getMatrixAt(0, matrix)
    matrix.decompose(actualPosition, actualQuaternion, actualScale)
    expect(actualPosition.toArray()).toEqual(position.toArray())
    expect(Math.abs(actualQuaternion.dot(quaternion))).toBeCloseTo(1, 6)
    expect(actualScale.x).toBeCloseTo(4, 6)
    expect(actualScale.y).toBeCloseTo(5, 6)
    expect(actualScale.z).toBeCloseTo(6, 6)
  })

})

describe('coalesceCylinderRuns', () => {
  it('merges only contiguous same-color domains on the same helix', () => {
    const rows = [
      { helixId: 'h1', bp_lo: 0, bp_hi: 4, t0: 0, t1: .25, defaultColor: 1 },
      { helixId: 'h1', bp_lo: 5, bp_hi: 9, t0: .25, t1: .5, defaultColor: 1 },
      { helixId: 'h1', bp_lo: 10, bp_hi: 12, t0: .5, t1: .65, defaultColor: 2 },
      { helixId: 'h2', bp_lo: 0, bp_hi: 3, t0: 0, t1: 1, defaultColor: 1 },
    ]
    const runs = coalesceCylinderRuns(rows)
    expect(runs).toHaveLength(3)
    expect(runs[0]).toMatchObject({ helixId: 'h1', bp_lo: 0, bp_hi: 9, t0: 0, t1: .5, color: 1 })
    expect(runs[0].domains).toHaveLength(2)
  })

  it('does not bridge a physical bp gap even when colors match', () => {
    expect(coalesceCylinderRuns([
      { helixId: 'h1', bp_lo: 0, bp_hi: 2, t0: 0, t1: .2, defaultColor: 7 },
      { helixId: 'h1', bp_lo: 5, bp_hi: 8, t0: .5, t1: .8, defaultColor: 7 },
    ])).toHaveLength(2)
  })
})

// A nucleotide with just the fields orderStrandNucleotides reads. `z` stands in for
// the axial coordinate so we can assert monotone backbone threading through a loop.
const nuc = (bp, dir, z, copyHint = 0) => ({
  helix_id: 'h0', bp_index: bp, direction: dir, domain_index: 0, z, _copyHint: copyHint,
})

// A loop insertion at bp5 emits copies in ascending-axial (emission) order: copy0 low,
// copy1 high. The geometry list yields them in that order regardless of strand direction.
const loopCopiesAscending = (dir, z0, z1) => [nuc(5, dir, z0, 0), nuc(5, dir, z1, 1)]

describe('orderStrandNucleotides', () => {
  it('threads a FORWARD strand up the axis through a loop (copies 0→1)', () => {
    // built out of order on purpose; emission order of the loop copies is ascending
    const nucs = [nuc(4, 'FORWARD', 1.34), ...loopCopiesAscending('FORWARD', 1.50, 1.84), nuc(6, 'FORWARD', 2.00)]
    orderStrandNucleotides(nucs)
    const zs = nucs.map(n => n.z)
    expect(zs).toEqual([...zs].sort((a, b) => a - b))         // strictly ascending
  })

  it('threads a REVERSE strand down the axis through a loop (copies 1→0)', () => {
    // REVERSE strand descends bp (6→5→4); the loop copies must be visited high→low
    const nucs = [nuc(6, 'REVERSE', 2.00), ...loopCopiesAscending('REVERSE', 1.50, 1.84), nuc(4, 'REVERSE', 1.34)]
    orderStrandNucleotides(nucs)
    const zs = nucs.map(n => n.z)
    expect(zs).toEqual([...zs].sort((a, b) => b - a))         // strictly descending — no zig-zag
    // the high copy (copy 1) is threaded before the low copy (copy 0)
    const copies = nucs.filter(n => n.bp_index === 5)
    expect(copies.map(n => n._copyHint)).toEqual([1, 0])
  })

  it('is a no-op ordering for a strand without loops (plain ascending FORWARD)', () => {
    const nucs = [nuc(2, 'FORWARD', 0.7), nuc(0, 'FORWARD', 0.0), nuc(1, 'FORWARD', 0.34)]
    orderStrandNucleotides(nucs)
    expect(nucs.map(n => n.bp_index)).toEqual([0, 1, 2])
  })
})

describe('directConnectedOverhangIds', () => {
  it('selects bound direct connections and skips linker/unbound records', () => {
    const ids = directConnectedOverhangIds({
      overhang_bindings: [
        { bound: true, connection_type: 'root-to-root', driver_oh_id: 'ohA', driven_oh_id: 'ohB' },
        { bound: false, connection_type: 'end-to-root', driver_oh_id: 'free', driven_oh_id: 'skip' },
        { bound: true, connection_type: 'root-to-root-dsdna-linker', overhang_a_id: 'linkA', overhang_b_id: 'linkB' },
        { bound: true, connection_type: 'end-to-root', overhang_a_id: 'legacyA', overhang_b_id: 'legacyB' },
      ],
      duplexes: [
        { bound: true, connection_type: 'root-to-root', left: { overhang_id: 'dxA' }, right: { overhang_id: 'dxB' } },
      ],
    })
    expect([...ids].sort()).toEqual(['dxA', 'dxB', 'legacyA', 'legacyB', 'ohA', 'ohB'])
  })
})

// ── The instanceAlpha compositor ──────────────────────────────────────────────
// buildHelixObjects builds a live scene graph and its 69 controller methods are not
// unit-testable without WebGL, so these are source-text assertions — the same
// approach design_renderer.test.js uses for cross-list agreement. They exist because
// the failure mode here is silent: an alpha writer that misses a mesh family, or a
// data array that lacks the field a lookup needs, produces no error at all — just
// geometry that quietly refuses to fade.

const HR = readFileSync(resolve(process.cwd(), 'src/scene/helix_renderer.js'), 'utf8')

/** Body of a named function declaration, brace-matched. */
function fnBody(src, name) {
  const start = src.indexOf(`function ${name}(`)
  if (start < 0) return null
  const open = src.indexOf('{', start)
  let depth = 0
  for (let j = open; j < src.length; j++) {
    if (src[j] === '{') depth++
    else if (src[j] === '}' && --depth === 0) return src.slice(open, j + 1)
  }
  return null
}

describe('presentation paths preserve live geometry', () => {
  it('routes bead sizing/highlighting and slab refresh through live matrices', () => {
    const beadScale = fnBody(HR, '_setBeadScale')
    expect(beadScale).toContain('rescaleInstanceInPlace')
    expect(beadScale).not.toContain('compose(entry.pos')

    const slabParams = fnBody(HR, 'applySlabParams')
    expect(slabParams).toContain('rescaleInstanceInPlace')
    expect(slabParams).not.toContain('_slabCenterAt')

    const stapleVisibility = HR.slice(HR.indexOf('setStapleVisibility(visible)'))
    expect(stapleVisibility.slice(0, 2400)).toContain('_preHideSlabMatrix')
    expect(stapleVisibility.slice(0, 2400)).not.toContain('_slabCenterAt')
  })
})

describe('instanceAlpha coverage', () => {
  it('every cylinder data array carries domainIndex', () => {
    // Without it, _clusterAlphaForCyl can only ever resolve the helix-level key —
    // a domain-level cluster silently fails to fade that cylinder. The curved
    // arrays lacked this until 2026-08-01.
    for (const arr of ['_domainCylData', '_overhangCylData',
                       '_curvedDomainCylData', '_curvedOvhgCylData']) {
      const push = HR.slice(HR.indexOf(`${arr}.push({`))
      expect(push.slice(0, 400), arr).toContain('domainIndex')
    }
  })

  it('curved TUBE meshes carry the identity a per-domain factor needs', () => {
    const ud = HR.slice(HR.indexOf('tubeMesh.userData = {'))
    expect(ud.slice(0, 300)).toContain('domainIndex')
    expect(ud.slice(0, 300)).toContain('bp_lo')      // for the rep-override column test
  })

  it('binding cylinders have an instance→domain array at all', () => {
    // There was none: bindIdx was never recorded, which is exactly why binding
    // cylinders were the one cylinder family with no per-instance alpha.
    expect(HR).toContain('_bindingCylData')
    const push = HR.slice(HR.indexOf('_bindingCylData.push({'))
    expect(push.slice(0, 300)).toContain('cylIdx')
    expect(push.slice(0, 300)).toContain('domainIndex')
  })

  it('renders conjugate oh_binder strands as the opposite cylinder half', () => {
    // VoltronCoreArm OH7 uses an oh_binder rather than a linker strand. Treating
    // it as an ordinary domain produced a second stale full cylinder.
    expect(HR).toContain("strand.strand_type === 'oh_binder'")
    expect(HR).toContain('dom.binds_overhang_id != null')
  })

  it('preserves authoritative moved-overhang endpoints during deform lerp', () => {
    const body = HR.slice(HR.indexOf('// 5b. Straight-helix overhang cylinders (LOD) — same approach.'))
    expect(body.slice(0, 4500)).toContain('dom.wsStart && dom.wsEnd')
    expect(body.slice(0, 4500)).toContain('dom.wsStart.x')
    expect(HR).toContain('getOverhangCylinderDiagnostics(overhangId)')
  })

  it('the installer covers every mesh the alpha writers drive', () => {
    // Cross-list agreement: a mesh written but never installed is a silent no-op,
    // because _setCylAlpha/_setEntryAlpha return early with no attribute.
    const install = fnBody(HR, '_ensureAlphaInstalled')
    expect(install).not.toBeNull()
    for (const mesh of [
      'iSpheres', 'iCubes', 'iFluoros', 'iCones', 'iSlabs', 'iSlabConnectors',
      'iHelixCylinders', 'iOverhangCylinders', 'iOverhangFullCylinders',
      'iLinkerBridgeCylinders', 'iLinkerBindingCylinders',
      'iCurvedHelixCylinders', 'iCurvedOverhangCylinders', 'iCurvedOverhangFullCylinders',
    ]) {
      expect(install, mesh).toContain(`_installInstanceAlpha(${mesh})`)
    }
  })

  it('installs the complete alpha channel when strands become reference geometry', () => {
    // Simulate hides reference geometry independently of the selected representation.
    // The old setter installed bead/slab alpha only, so cylinder representations leaked.
    const setter = HR.slice(HR.indexOf('setReferenceStrands(idSet'))
    expect(setter.slice(0, 900)).toContain('_ensureAlphaInstalled()')
  })

  it('no longer skips the impostor beads', () => {
    // iSpheres/iFluoros used to be skipped outright under impostors, so bead alpha
    // was a silent no-op with ?impostors=1.
    expect(HR).not.toContain('if (!_useImpostors) _installInstanceAlpha')
  })

  it('routes impostor materials through their own composed patch', () => {
    // applyInstanceAlphaMaterial ASSIGNS onBeforeCompile; on an impostor that would
    // wipe the billboard + gl_FragDepth patch and leave flat quads.
    const body = fnBody(HR, '_installInstanceAlpha')
    expect(body).toContain('isImpostor')
    expect(body).toContain('enableImpostorInstanceAlpha')
    expect(body).toContain('installInstanceAlphaGeometry')
  })

  it('both alpha writers drive the curved + binding families', () => {
    // When an override is active ONLY _applyRepOverrides runs, and when it is not
    // ONLY _applyAlphaChannel runs. A family handled by just one reverts the moment
    // the user toggles an override.
    expect(fnBody(HR, '_applyAlphaChannel')).toContain('_refreshCurvedAlpha()')
    expect(fnBody(HR, '_applyRepOverrides')).toContain('_refreshCurvedAlpha()')
  })

  it('the deform cross-fade composes instead of writing opacity absolutely', () => {
    // The cross-fade owns material.opacity on the curved meshes. Writing a
    // per-domain factor there directly got clobbered on the next lerp frame — the
    // reason deformed designs showed no cluster fade at cylinders rep.
    // Exactly ONE raw write to a tube material may exist: the compositor's own,
    // which multiplies the stored base by the per-domain factor.
    const rawTubeWrites = [...HR.matchAll(/_fadeMat\(mesh\.material,/g)]
    expect(rawTubeWrites.length).toBe(1)
    expect(fnBody(HR, '_fadeCurvedTube')).toContain('_fadeMat(mesh.material,')
    expect(fnBody(HR, '_fadeCurvedTube')).toContain('crossfadeBase')
    expect(fnBody(HR, '_fadeCurvedTube')).toContain('_curvedTubeFactor')
    // The proxies never take a raw write at all — they go through _fadeCurvedProxy.
    expect(HR).not.toMatch(/_fadeMat\(iCurved\w+\.material,/)
  })

  it('the curved proxy keeps _fadeMat’s depth contract', () => {
    // depthWrite only when opaque — an opacity-0 depth-writing mesh is an invisible
    // occluder (LESSONS D8). But it must stay in the transparent queue while a
    // per-instance factor is live, or instanceAlpha has nothing to blend into.
    const body = fnBody(HR, '_fadeCurvedProxy')
    expect(body).toContain('_fadeMat(mat, base)')
    expect(body).toMatch(/_anyAlpha\(\)/)
  })

  it('the rep-override column test is shared, not duplicated', () => {
    // _cylRepVis is consulted by both the instanced writers and the curved-tube
    // compositor; a second copy would let the two disagree about which columns
    // resolve to cylinders.
    expect(fnBody(HR, '_cylRepVis')).toContain('_effCol')
    expect(fnBody(HR, '_cylFactor')).toContain('_cylRepVis')
    expect(fnBody(HR, '_curvedTubeFactor')).toContain('_cylRepVis')
  })
})

describe('overhang cylinder instance lookup', () => {
  it('builds direct half/full instance maps and getters do not scan domain data', () => {
    const indexBody = fnBody(HR, '_ensureCylinderDomainIndex')
    expect(indexBody).toContain('_overhangHalfByInstance = new Map()')
    expect(indexBody).toContain('_overhangFullByInstance = new Map()')

    for (const [getter, map] of [
      ['getOverhangCylinderDomainAt(instanceId)', '_overhangHalfByInstance.get(instanceId)'],
      ['getOverhangFullCylinderDomainAt(instanceId)', '_overhangFullByInstance.get(instanceId)'],
    ]) {
      const start = HR.indexOf(getter)
      const body = HR.slice(start, HR.indexOf('\n    },', start))
      expect(start, getter).toBeGreaterThan(-1)
      expect(body).toContain(map)
      expect(body).not.toContain('.find(')
    }
  })
})

describe('cylinder visibility and glow hot-path indexes', () => {
  it('indexes assigned nucleotides by domain instead of filtering all geometry per cylinder', () => {
    const build = fnBody(HR, '_ensureAssignedNucsByDomain')
    const lookup = fnBody(HR, '_hiddenAlphaForCyl')
    expect(build).toContain('_assignedNucsByDomain = new Map()')
    expect(build).toContain('for (const nuc of assignedGeometry)')
    expect(lookup).toContain('_assignedNucsByDomain.get(')
    expect(lookup).not.toContain('assignedGeometry.filter(')
  })

  it('resolves selected domain refs directly to glow entries without sweeping cylinder arrays', () => {
    const resolve = fnBody(HR, '_refsToCylinderEntries')
    const write = fnBody(HR, '_writeCylGlow')
    expect(resolve).toContain('_cylEntriesByDomainRef.get(')
    expect(resolve).not.toContain('_domainCylData.filter(')
    expect(resolve).not.toContain('_overhangCylData.filter(')
    expect(write).toContain('for (const dom of domEntries)')
    expect(write).not.toContain('.has(dom.cylIdx)')
  })
})

describe('slab build tolerates nucleotides without a base site', () => {
  it('skips a nucleotide with no base_position instead of spreading undefined', () => {
    // Injected non-design nucleotides (oxDNA surface capture strands) are built in
    // the frontend, so nothing guarantees the backend's full nucleotide record. Before
    // this guard `new THREE.Vector3(...nuc.base_position)` threw out of the entire
    // rebuild, and the exception unwound through the setup card's onChange — which
    // then stopped tracking its own fields, so the 3D froze on a stale spec.
    const start = HR.indexOf("// Extension beads have no base-pair slabs.")
    expect(start).toBeGreaterThan(-1)
    const region = HR.slice(start, HR.indexOf('new THREE.Vector3(...nuc.base_normal)', start))
    expect(region).toContain('if (!nuc.base_position) continue')
  })
})

describe('slab connector colour parity', () => {
  it('the shared recolour path updates a slab connector with its slab', () => {
    const body = fnBody(HR, '_setInstColor')
    expect(body).toContain('entry.connectorMesh.setColorAt(entry.connectorId')
  })

  it('geometry refresh mirrors the current slab colour instead of its default', () => {
    const body = fnBody(HR, '_refreshSlabConnectors')
    expect(body).toContain('iSlabs.getColorAt(slab.id, _connectorColor)')
    expect(body).toContain('iSlabConnectors.setColorAt(i, _connectorColor)')
    expect(body).not.toContain('slab.defaultColor')
  })

  it('flex-map recolouring captures and recolours both slab and connector', () => {
    const start = HR.indexOf('applyScalarColors(colorByKey)')
    const body = HR.slice(start, HR.indexOf('clearScalarColors()', start))
    expect(body).toContain('recolor(slab.instMesh, slab.id, hex)')
    expect(body).toContain('recolor(slab.connectorMesh, slab.connectorId, hex)')
    const dirty = fnBody(HR, '_flagScalarColorMeshes')
    expect(dirty).toContain('iSlabConnectors')
  })
})

describe('cluster transforms keep the complete slab frame rigid', () => {
  const captureStart = HR.indexOf('\n    captureClusterBase(')
  const applyStart = HR.indexOf('\n    applyClusterTransform(', captureStart)
  const commitStart = HR.indexOf('\n    commitClusterPositions(', applyStart)
  const captureBody = HR.slice(captureStart, applyStart)
  const applyBody = HR.slice(applyStart, commitStart)
  const commitBody = HR.slice(commitStart, HR.indexOf('\n    applyBridgeNucsUpdate(', commitStart))

  it('snapshots and transforms the rendered slab center instead of re-solving from stale geometry', () => {
    expect(captureBody).toContain('slab.instMesh.getMatrixAt(slab.id, _tMatrix)')
    expect(captureBody).toContain('center: renderedCenter')
    expect(applyBody).toContain('_clusterV.copy(baseData.center)')
    expect(applyBody).toContain('slab.center.set(')
    expect(applyBody).not.toContain('const center_ = _slabCenterAt(slab')
  })

  it('commits every position/orientation field needed to reconstruct that slab frame', () => {
    expect(commitBody).toContain('entry.nuc.backbone_position')
    expect(commitBody).toContain('slab.nuc.base_position')
    expect(commitBody).toContain('slab.nuc.base_normal')
    expect(commitBody).toContain('slab.nuc.axis_tangent')
  })

  it('rotates slab centers and orientations from the same captured rigid frame', () => {
    expect(captureBody).toContain('center: renderedCenter')
    expect(captureBody).toContain('quat: slab.quat.clone()')
    expect(applyBody).toContain('_clusterV.copy(baseData.center).sub(centerVec).applyQuaternion(incrRotQuat)')
    expect(applyBody).toContain('_clusterQ.multiplyQuaternions(incrRotQuat, baseData.quat)')
  })
})

describe('authoritative partial geometry preserves the applied bead preview', () => {
  const start = HR.indexOf('patchNucleotides(partialNucs')
  const end = HR.indexOf('\n    setStrandColor(', start)
  const body = HR.slice(start, end)

  it('copies saved backbone coordinates instead of patching metadata only', () => {
    expect(body).toContain("'backbone_position', 'base_position', 'base_normal', 'axis_tangent'")
    expect(body).toContain('entry.nuc[field] = [...nuc[field]]')
    expect(body).toContain('data.bb.push(nuc.backbone_position)')
  })

  it('rewrites bead matrices through the same updater used by undo/redo positions', () => {
    expect(body).toContain('this.applyPositionsUpdate(positionsByHelix)')
    const updater = HR.slice(HR.lastIndexOf('applyPositionsUpdate(positionsByHelix'))
    expect(updater).toContain('syncPatchedBeadPosition(entry, u.bb)')
    expect(updater).toContain('entry.instMesh.setMatrixAt(entry.id, _tMatrix)')
  })

  it('keeps a live-previewed bead at the identical saved Apply coordinate', () => {
    const previewed = new THREE.Vector3(8.125, -3.75, 11.5)
    const entry = { pos: previewed.clone() }
    const beforeApply = entry.pos.clone()
    syncPatchedBeadPosition(entry, previewed.toArray())
    expect(entry.pos.distanceTo(beforeApply)).toBeLessThan(1e-12)

    // A native/stale response would make this assertion fail visibly.
    const native = new THREE.Vector3(0, 0, 1.7)
    expect(entry.pos.distanceTo(native)).toBeGreaterThan(1)
  })
})

describe('domain-scoped cluster axis transforms', () => {
  const captureStart = HR.indexOf('\n    captureClusterBase(')
  const applyStart = HR.indexOf('\n    applyClusterTransform(', captureStart)
  const captureBody = HR.slice(captureStart, applyStart)
  const applyBody = HR.slice(applyStart, HR.indexOf('\n    commitClusterPositions(', applyStart))

  it('matches atomic axis segments against every owning domain', () => {
    expect(HR).toContain('domainIds:    bs?.domain_ids')
    expect(captureBody).toContain('seg.domainIds.some(')
    expect(captureBody).not.toContain('domainKeySet.has(`${seg.strandId}:${seg.domainIndex}`)')
  })

  it('moves only captured curved segment tubes with their corresponding axis interval', () => {
    expect(captureBody).toContain('tubePos: seg.tubeMesh?.position.clone()')
    expect(captureBody).toContain('tubeQuat: seg.tubeMesh?.quaternion.clone()')
    expect(applyBody).toContain('if (seg.tubeMesh && snap.tubePos && snap.tubeQuat)')
    expect(applyBody).toContain('seg.tubeMesh.quaternion.multiplyQuaternions(incrRotQuat, snap.tubeQuat)')
  })
})
