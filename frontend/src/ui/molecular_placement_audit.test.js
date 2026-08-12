import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as THREE from 'three'

import {
  auditDefectRows,
  auditMetricRows,
  auditStrandColorMap,
  copyAuditCameraState,
  filterAuditAtomData,
  initMolecularPlacementAudit,
} from './molecular_placement_audit.js'

const DIAGNOSTICS = {
  piercing: { n_pierced: 0, pierced: [] },
  bonds: { max_length_nm: 0.17, n_overstretched: 0, overstretched: [] },
  n_clashes: 0,
  clashes: [],
}

function auditBundle() {
  const atoms = [
    { serial: 0, name: 'P', element: 'P', chain_id: 'A', seq_num: 9, x: 0, y: 0, z: 0, crossover_id: 'xo-1' },
    { serial: 1, name: "C1'", element: 'C', chain_id: 'A', seq_num: 9, x: 1, y: 0, z: 0, crossover_id: 'xo-1' },
    { serial: 2, name: 'N1', element: 'N', chain_id: 'B', seq_num: 12, x: 2, y: 0, z: 0, crossover_id: 'xo-2' },
  ]
  return {
    provider: { id: 'geometric-baseline-v1', label: 'Raw geometric baseline' },
    current_design: { helices: [], crossovers: [] },
    candidate_design: { helices: [], crossovers: [] },
    current: { atoms, bonds: [[0, 1], [1, 2]], diagnostics: DIAGNOSTICS },
    candidate: {
      atoms: atoms.map(atom => ({ ...atom, x: atom.serial === 2 ? 2.2 : atom.x })),
      bonds: [[0, 1], [1, 2]],
      diagnostics: {
        ...DIAGNOSTICS,
        n_clashes: 1,
        clashes: [{ serials: [0, 2], distance_nm: 0.0412 }],
      },
    },
    affected_atom_serials: [1, 2],
    defect_atom_serials: { current: [], candidate: [0, 2] },
    displacement: {
      n_displaced: 1,
      max_nm: 0.2,
      rms_nm: 0.2,
      vectors: [{ serial: 2, from: [2, 0, 0], to: [2.2, 0, 0], distance_nm: 0.2 }],
    },
    nucleotides: [],
    helix_axes: [],
  }
}

beforeEach(() => {
  document.body.innerHTML = '<button id="menu-help-molecular-placement-audit"></button>'
})

describe('molecular placement audit data helpers', () => {
  it('isolates affected atoms and preserves only bonds fully inside that subset', () => {
    const filtered = filterAuditAtomData(auditBundle().current, [0, 2])
    expect(filtered.atoms.map(atom => atom.name)).toEqual(['P', 'N1'])
    expect(filtered.atoms.map(atom => atom.serial)).toEqual([0, 1])
    expect(filtered.bonds).toEqual([])
  })

  it('formats current-to-candidate diagnostic metrics', () => {
    const rows = auditMetricRows(auditBundle())
    expect(rows).toContainEqual(['Displaced atoms', 1, ''])
    expect(rows).toContainEqual(['Max displacement', '0.200 nm', ''])
    expect(rows).toContainEqual(['Ring piercings', '0 → 0', 'good'])
    expect(rows).toContainEqual(['Clashes', '0 → 1', 'bad'])
    expect(rows.find(([label]) => label === 'Wound junctions')).toBeUndefined()
  })

  it('identifies the exact side, atoms, and separation shown for a clash', () => {
    expect(auditDefectRows(auditBundle())).toEqual([{
      side: 'candidate',
      kind: 'clash',
      text: 'Candidate CLASH · A9:P ↔ B12:N1 · 0.041 nm',
    }])
  })

  it('copies the exact camera position, target, orbit, and zoom', () => {
    const source = {
      camera: new THREE.PerspectiveCamera(),
      controls: { target: new THREE.Vector3(0, 0, 0) },
    }
    source.camera.position.set(10, 0, 0)
    source.camera.near = 0.02
    source.camera.far = 500
    source.camera.zoom = 1.7
    const target = {
      camera: new THREE.PerspectiveCamera(),
      controls: { target: new THREE.Vector3(1, 2, 3), update: vi.fn() },
    }
    target.camera.position.set(1, 2, 8)

    copyAuditCameraState(source, target)

    expect(target.camera.position.toArray()).toEqual([10, 0, 0])
    expect(target.controls.target.toArray()).toEqual([0, 0, 0])
    expect(target.camera.near).toBe(0.02)
    expect(target.camera.far).toBe(500)
    expect(target.camera.zoom).toBe(1.7)
    expect(target.controls.update).toHaveBeenCalledOnce()
  })

  it('uses scaffold, persisted, and active strand colors for atomistic panels', () => {
    const bundle = {
      current_design: {
        id: 'audit-color-test',
        strands: [
          { id: 'sc', strand_type: 'scaffold', color: null },
          { id: 's1', strand_type: 'staple', color: '#123456' },
          { id: 's2', strand_type: 'staple', color: null },
        ],
        crossovers: [],
      },
      nucleotides: [
        { strand_id: 'sc', strand_type: 'scaffold' },
        { strand_id: 's1', strand_type: 'staple' },
        { strand_id: 's2', strand_type: 'staple' },
      ],
    }
    const colors = auditStrandColorMap(bundle, { strandColors: { s2: '#abcdef' } })
    expect(colors.get('sc')).toBe(0x0070bb)
    expect(colors.get('s1')).toBe(0x123456)
    expect(colors.get('s2')).toBe(0xabcdef)
  })

  it('names the exact pierced bond and ring shown in the defect panel', () => {
    const bundle = auditBundle()
    bundle.candidate.diagnostics.n_clashes = 0
    bundle.candidate.diagnostics.clashes = []
    bundle.candidate.diagnostics.piercing = {
      n_pierced: 1,
      pierced: [{ bond: "A9:O3'-A10:P", ring: 'B9DT[xb0]', bond_serials: [0, 1], ring_serials: [2] }],
    }
    expect(auditDefectRows(bundle)).toEqual([{
      side: 'candidate',
      kind: 'piercing',
      text: "Candidate PIERCING · A9:O3'-A10:P through B9DT[xb0]",
    }])
  })
})

describe('Molecular Placement Audit modal', () => {
  it('opens from Help with four panels and Full/Ball and Stick on every panel', async () => {
    const instances = []
    const viewerFactory = vi.fn((_host, panelId, _bundle, initialRepresentation) => {
      const viewer = {
        panelId,
        initialRepresentation,
        camera: new THREE.PerspectiveCamera(),
        controls: {
          target: new THREE.Vector3(),
          addEventListener: vi.fn(),
          update: vi.fn(),
        },
        setRepresentation: vi.fn(),
        fit: vi.fn(),
        dispose: vi.fn(),
      }
      instances.push(viewer)
      return viewer
    })
    const setMenuToggle = vi.fn()
    const audit = initMolecularPlacementAudit({
      fetchAudit: vi.fn().mockResolvedValue(auditBundle()),
      viewerFactory,
      setMenuToggle,
    })

    document.getElementById('menu-help-molecular-placement-audit').click()
    await vi.waitFor(() => expect(audit.element.querySelectorAll('.mpa-panel')).toHaveLength(4))

    expect([...audit.element.querySelectorAll('.mpa-panel')].map(p => p.dataset.panel))
      .toEqual(['current', 'candidate', 'difference', 'defects'])
    expect(audit.element.querySelector('[data-panel="defects"] .mpa-panel-title').textContent)
      .toBe('Piercings / clashes')
    for (const select of audit.element.querySelectorAll('.mpa-representation')) {
      expect([...select.options].map(option => [option.value, option.textContent]))
        .toEqual([['full', 'Full'], ['ballstick', 'Ball and Stick']])
    }
    expect(audit.element.dataset.provider).toBe('geometric-baseline-v1')
    expect(audit.element.dataset.affectedAtoms).toBe('2')
    expect(instances.map(viewer => viewer.initialRepresentation))
      .toEqual(['full', 'full', 'ballstick', 'ballstick'])

    expect(audit.element.querySelector('.mpa-defect-status').textContent)
      .toContain('Candidate CLASH · A9:P ↔ B12:N1 · 0.041 nm')
    expect(instances.every(viewer => viewer.controls.addEventListener.mock.calls.length === 1))
      .toBe(true)

    const defectSelect = audit.element.querySelector('[data-panel="defects"] select')
    defectSelect.value = 'full'
    defectSelect.dispatchEvent(new Event('change', { bubbles: true }))
    expect(instances[3].setRepresentation).toHaveBeenCalledWith('full')

    audit.element.querySelector('.mpa-reset').click()
    expect(instances[0].fit).toHaveBeenCalledOnce()
    expect(instances.slice(1).every(viewer => viewer.fit.mock.calls.length === 0)).toBe(true)
    audit.element.querySelector('.mpa-close').click()
    expect(instances.every(viewer => viewer.dispose.mock.calls.length === 1)).toBe(true)
    expect(setMenuToggle).toHaveBeenLastCalledWith('menu-help-molecular-placement-audit', false)
    audit.dispose()
  })

  it('renders backend errors as text and closes with Escape', async () => {
    const audit = initMolecularPlacementAudit({
      fetchAudit: vi.fn().mockRejectedValue(new Error('<b>not geometry</b>')),
    })
    await audit.show()
    const error = audit.element.querySelector('.mpa-error')
    expect(error.textContent).toBe('<b>not geometry</b>')
    expect(error.querySelector('b')).toBeNull()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(audit.isOpen()).toBe(false)
    audit.dispose()
  })
})
