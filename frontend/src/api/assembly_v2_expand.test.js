/**
 * Tests for the v2 wire-format expansion path in api/client.js.
 *
 * Phase 5 migrate-readers (path-to-thousands): the frontend prefers
 * ``format_version: 2`` + ``instances_v2`` + ``sources`` when present,
 * falling back to v1 ``instances`` for legacy payloads.
 *
 * Mocks the store + side-effect modules so we can drive
 * ``_syncFromAssemblyResponse`` in isolation and assert what lands in
 * ``store.currentAssembly``.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// ── Mocks ─────────────────────────────────────────────────────────────────────

const _stateBag = { current: {} }

vi.mock('../state/store.js', () => ({
  store: {
    getState: () => _stateBag.current,
    setState: (patch) => { _stateBag.current = { ..._stateBag.current, ...patch } },
    subscribe: vi.fn(),
  },
}))

vi.mock('../shared/broadcast.js', () => ({
  nadocBroadcast: { emit: vi.fn(), on: vi.fn() },
}))

vi.mock('../ui/toast.js', () => ({
  showToast: vi.fn(),
}))

vi.mock('../ui/op_progress.js', () => ({
  showOpProgress: vi.fn(),
  hideOpProgress: vi.fn(),
}))

// Stub localStorage so persistAssembly() doesn't blow up under jsdom.
beforeEach(() => {
  _stateBag.current = {}
  // jsdom provides localStorage; just clear it.
  if (typeof localStorage !== 'undefined') localStorage.clear()
})

// Imports AFTER the mocks are registered.
import {
  _syncFromAssemblyResponse,
  _expandV2Assembly,
} from './client.js'
import { store } from '../state/store.js'

// ── Helpers ───────────────────────────────────────────────────────────────────

const IDENTITY_T12 = [
  1, 0, 0, 0,
  0, 1, 0, 0,
  0, 0, 1, 0,
]

function identityV1Transform() {
  return {
    values: [
      1, 0, 0, 0,
      0, 1, 0, 0,
      0, 0, 1, 0,
      0, 0, 0, 1,
    ],
  }
}

function sampleSource() {
  return { type: 'file', path: 'workspace/ultimate_polymer_hinge.nadoc', sha256: null }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('_expandV2Assembly', () => {
  it('expands a v2-only payload (no legacy instances) into v1-shaped instances', () => {
    const src = sampleSource()
    const response = {
      assembly: {
        // No `instances` field at all — v2-only.
        format_version: 2,
        sources: { 'hinge_key': src },
        instances_v2: [
          // Minimal: only id, src_key, t12 → all other fields get defaults.
          { id: 'inst_A', src_key: 'hinge_key', t12: IDENTITY_T12 },
          // Override a few fields to confirm precedence over defaults.
          {
            id:                'inst_B',
            src_key:           'hinge_key',
            t12: [
              2, 0, 0, 10,
              0, 2, 0, 20,
              0, 0, 2, 30,
            ],
            name:              'Custom B',
            mode:              'rigid',
            visible:           false,
            fixed:             true,
            allow_part_joints: true,
            joint_states:      { 'j_main': 1.25 },
          },
        ],
        // Other top-level assembly fields stay untouched after expansion.
        joints:    [],
        camera_poses: [],
      },
    }

    _syncFromAssemblyResponse(response)
    const ca = store.getState().currentAssembly

    // length + presence
    expect(Array.isArray(ca.instances)).toBe(true)
    expect(ca.instances.length).toBe(2)

    // Inst A — minimal, all defaults applied.
    const a = ca.instances[0]
    expect(a.id).toBe('inst_A')
    expect(a.source).toEqual(src)            // resolved from sources map
    expect(a.transform.values.length).toBe(16)
    expect(a.transform.values).toEqual(identityV1Transform().values)
    expect(a.name).toBe('Part')
    expect(a.mode).toBe('flexible')
    expect(a.visible).toBe(true)
    expect(a.representation).toBe('full')
    expect(a.fixed).toBe(false)
    expect(a.allow_part_joints).toBe(false)
    expect(a.base_transform).toBe(null)
    expect(a.joint_states).toEqual({})
    expect(a.cluster_transform_overrides).toEqual([])
    expect(a.interface_points).toEqual([])

    // Inst B — overrides applied.
    const b = ca.instances[1]
    expect(b.id).toBe('inst_B')
    expect(b.source).toEqual(src)            // same src_key → same source instance
    expect(b.transform.values).toEqual([
      2, 0, 0, 10,
      0, 2, 0, 20,
      0, 0, 2, 30,
      0, 0, 0, 1,
    ])
    expect(b.name).toBe('Custom B')
    expect(b.mode).toBe('rigid')
    expect(b.visible).toBe(false)
    expect(b.fixed).toBe(true)
    expect(b.allow_part_joints).toBe(true)
    expect(b.joint_states).toEqual({ 'j_main': 1.25 })

    // v2-only fields are stripped from the canonical store shape.
    expect(ca.format_version).toBeUndefined()
    expect(ca.instances_v2).toBeUndefined()
    expect(ca.sources).toBeUndefined()

    // Untouched top-level keys carry through.
    expect(ca.joints).toEqual([])
    expect(ca.camera_poses).toEqual([])
  })

  it('passes through a v1-only legacy payload unchanged', () => {
    const v1Instance = {
      id:                          'legacy_X',
      name:                        'Hinge 1',
      source:                      sampleSource(),
      transform:                   identityV1Transform(),
      base_transform:              null,
      mode:                        'flexible',
      visible:                     true,
      representation:              'full',
      fixed:                       false,
      allow_part_joints:           false,
      joint_states:                {},
      cluster_transform_overrides: [],
      interface_points:            [],
    }
    const response = {
      assembly: {
        // No format_version, no instances_v2, no sources — legacy .nass shape.
        instances: [v1Instance],
        joints:    [],
      },
    }

    _syncFromAssemblyResponse(response)
    const ca = store.getState().currentAssembly

    expect(ca.instances.length).toBe(1)
    expect(ca.instances[0]).toEqual(v1Instance)  // unchanged passthrough
    expect(ca.joints).toEqual([])
  })

  it('skips v2 instances whose src_key is missing and warns', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const src = sampleSource()
    const response = {
      assembly: {
        format_version: 2,
        sources: { 'good_key': src },  // 'bad_key' is intentionally absent
        instances_v2: [
          { id: 'inst_ok',  src_key: 'good_key', t12: IDENTITY_T12 },
          { id: 'inst_bad', src_key: 'bad_key',  t12: IDENTITY_T12 },
        ],
      },
    }

    _syncFromAssemblyResponse(response)
    const ca = store.getState().currentAssembly

    expect(ca.instances.length).toBe(1)
    expect(ca.instances[0].id).toBe('inst_ok')
    expect(warnSpy).toHaveBeenCalledTimes(1)
    expect(warnSpy.mock.calls[0][0]).toMatch(/bad_key/)
    warnSpy.mockRestore()
  })

  it('uses inline `source` on a v2 entry when `src_key` is absent', () => {
    const inlineSrc = sampleSource()
    const response = {
      assembly: {
        format_version: 2,
        sources: {},
        instances_v2: [
          { id: 'inst_inline', source: inlineSrc, t12: IDENTITY_T12 },
        ],
      },
    }

    _syncFromAssemblyResponse(response)
    const ca = store.getState().currentAssembly

    expect(ca.instances.length).toBe(1)
    expect(ca.instances[0].source).toEqual(inlineSrc)
  })

  it('falls back to v1 when format_version is 2 but v2 fields are incomplete', () => {
    // Defensive: a malformed dual-write payload that claims v2 but doesn't have
    // instances_v2 should still load via v1 rather than crashing or losing data.
    const v1Instance = {
      id:        'partial',
      source:    sampleSource(),
      transform: identityV1Transform(),
      name:      'Part',
      mode:      'flexible',
      visible:   true,
      representation: 'full',
      fixed:     false,
      allow_part_joints: false,
      base_transform: null,
      joint_states: {},
      cluster_transform_overrides: [],
      interface_points: [],
    }
    const response = {
      assembly: {
        format_version: 2,         // claims v2
        // instances_v2 + sources absent
        instances: [v1Instance],   // but v1 is here
      },
    }

    _syncFromAssemblyResponse(response)
    const ca = store.getState().currentAssembly
    expect(ca.instances.length).toBe(1)
    expect(ca.instances[0]).toEqual(v1Instance)
  })

  it('_expandV2Assembly is a pure function: returns a new object for v2, leaves v1 unchanged', () => {
    // v1 passthrough → reference-equal
    const v1 = { instances: [], joints: [] }
    expect(_expandV2Assembly(v1)).toBe(v1)

    // v2 expansion → distinct object, distinct instances array
    const v2 = {
      format_version: 2,
      sources: { k: sampleSource() },
      instances_v2: [{ id: 'x', src_key: 'k', t12: IDENTITY_T12 }],
    }
    const out = _expandV2Assembly(v2)
    expect(out).not.toBe(v2)
    expect(out.instances).toBeDefined()
    expect(out.format_version).toBeUndefined()
  })
})
