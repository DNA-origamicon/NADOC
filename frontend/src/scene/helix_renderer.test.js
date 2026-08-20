import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { coalesceCylinderRuns, directConnectedOverhangIds, orderStrandNucleotides } from './helix_renderer.js'

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
