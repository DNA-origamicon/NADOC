/**
 * atom_table.js — one indexed view over atom records, whatever shape they arrived in.
 *
 * WHY: the oxDNA display bundle ships ~330k atoms.  As JSON dicts that is ~112 MB on the
 * wire and 330k JavaScript objects out of `JSON.parse` — the dominant cost of showing an
 * atomistic rep, far above anything the GPU does.  The columnar/binary bundle
 * (`atomistic_bundle_bin.js`) replaces that with a handful of typed arrays plus small
 * interned string tables.
 *
 * But the renderer is fed by SIX other producers (design atomistic, protein atomistic,
 * instance atomistic, filtered subsets, baked NAMD frames, live MD websocket) that all
 * still hand over plain object arrays, and consumers like `color_resolver` /
 * `atomOffset` / the protein predicates read atoms as duck-typed objects.  Converting all
 * of them at once would be a far riskier change than the one that pays.
 *
 * So: AtomTable accepts EITHER shape and hides the difference.
 *   - `get(i)`         → an atom-like object, for anything that reads several fields
 *                        (colour resolution, predicates, atomOffset).
 *   - `materialize(i)` → a PLAIN OWNED object, for anything that keeps the reference.
 *   - `x(i)/y(i)/z(i)/element(i)/helixId(i)` → scalars, for the hot geometry loops.
 *
 * ⚠️  THE FLYWEIGHT CONTRACT.  For a columnar table `get(i)` returns a SHARED, MUTABLE
 * view — the same object every call, re-pointed at row `i`.  That is what buys us the
 * "no 330k objects" win.  It is valid only until the next `get()`.  Never store it, never
 * put it in an array, never close over it, never return it to a caller outside the loop.
 * If a reference has to outlive the iteration, use `materialize(i)`.  (For an object-array
 * table `get(i)` returns the real record, so a bug of this kind is INVISIBLE on the
 * design/protein/MD paths and only shows up on the oxDNA bundle — hence this shouting.)
 */

/** Fields the frontend actually reads off an atom. The other 7 the backend used to send
 *  (name, residue, chain_id, seq_num, is_modified, crossover_id, extra_base_k) are not
 *  read anywhere in src/ and are absent from the columnar payload by design. */
export const ATOM_FIELDS = [
  'serial', 'element', 'x', 'y', 'z',
  'strand_id', 'helix_id', 'bp_index', 'direction', 'aux_helix_id', 'aux_t',
]

/** True for a decoded columnar payload (see parseAtomisticBundleBin). */
export function isColumnarAtoms(data) {
  return !!data && data.columnar === true && typeof data.count === 'number'
}

/** Row view over a columnar payload. Property reads hit the typed arrays / intern
 *  tables directly, so no per-atom object is ever allocated. */
class ColumnarAtomView {
  constructor(c) { this._c = c; this._i = 0 }
  get serial()       { return this._i }
  get element()      { const c = this._c; return c.elementTable[c.elementIdx[this._i]] }
  get x()            { return this._c.x[this._i] }
  get y()            { return this._c.y[this._i] }
  get z()            { return this._c.z[this._i] }
  get strand_id()    { const c = this._c; return c.strandTable[c.strandIdx[this._i]] }
  get helix_id()     { const c = this._c; return c.helixTable[c.helixIdx[this._i]] }
  get bp_index()     { return this._c.bpIndex[this._i] }
  get direction()    { const c = this._c; return c.dirTable[c.dirIdx[this._i]] }
  get aux_helix_id() { const c = this._c; return c.auxHelixTable[c.auxHelixIdx[this._i]] }
  get aux_t()        { return this._c.auxT[this._i] }
}

function _columnarTable(c) {
  const view = new ColumnarAtomView(c)
  return {
    columnar: true,
    count: c.count,
    raw: c,
    get(i) { view._i = i; return view },
    materialize(i) {
      view._i = i
      const out = {}
      for (const f of ATOM_FIELDS) out[f] = view[f]
      return out
    },
    // Scalar fast paths — used by the geometry loops, which want numbers not objects.
    x(i) { return c.x[i] },
    y(i) { return c.y[i] },
    z(i) { return c.z[i] },
    serial(i) { return i },
    element(i) { return c.elementTable[c.elementIdx[i]] },
    helixId(i) { return c.helixTable[c.helixIdx[i]] },
  }
}

function _objectTable(atoms) {
  return {
    columnar: false,
    count: atoms.length,
    raw: atoms,
    get(i) { return atoms[i] },
    materialize(i) { return atoms[i] },     // already an owned record — no copy needed
    x(i) { return atoms[i].x },
    y(i) { return atoms[i].y },
    z(i) { return atoms[i].z },
    serial(i) { return atoms[i].serial },
    element(i) { return atoms[i].element },
    helixId(i) { return atoms[i].helix_id },
  }
}

/**
 * Wrap whatever `atomisticRenderer.update()` was handed.
 * @param {object|null} data  `{atoms: object[]}` (all legacy producers) or a decoded
 *                            columnar payload `{columnar:true, count, x, y, z, …}`.
 */
export function makeAtomTable(data) {
  if (isColumnarAtoms(data)) return _columnarTable(data)
  return _objectTable(Array.isArray(data?.atoms) ? data.atoms : (Array.isArray(data) ? data : []))
}
