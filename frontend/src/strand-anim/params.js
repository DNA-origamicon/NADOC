/**
 * Parameter state for the strand-animation playground.
 *
 * A tiny observable: get/set/subscribe/snapshot. No framework, no store
 * dependency — this page is fully standalone.
 */

export const DEFAULTS = {
  // ── Strand model ──
  N: 21,                 // base pairs              [2 .. 200]
  rise: 0.334,           // dsDNA rise (nm/bp)      [0.30 .. 0.45]
  W: 2.0,                // duplex width (nm)        [0.5 .. 4.0]
  thetaDeg: 30,          // splay half-angle (deg)   [0 .. 85]
  twistDeg: 34.3,        // helix twist (deg/bp)     [0 .. 90]  (helical form only)
  meltBp: 2.0,           // melt transition width    [0 .. 6] bp (0 = sudden)
  armPull: 1.0,          // ssDNA contour ×rise      [1.0 .. 2.0]
  endFrom: 'right',      // which end unzips first   {left, right}
  forkToCenter: false,   // arms emanate from centerline vs the rails

  // ── Reaction coordinate ──
  phi: 1.0,              // fraction paired          [0 .. 1]
  direction: 'dehybridize', // play sweep sign       {hybridize, dehybridize}

  // ── Animation ──
  speed: 0.30,           // φ-units per second       [0.02 .. 2.0]
  easing: 'ease-in-out', // {linear, ease-in, ease-out, ease-in-out}
  loop: false,
  bounce: true,

  // ── Scenario + form ──
  scenario: 'unzip',     // {unzip, displacement}
  form: 'straight',      // {straight, helical}

  // ── Strand displacement ──
  toeholdBp: 6,          // toehold length (bp)      [0 .. 20]  (displacement only)
}

/**
 * @param {object} [overrides]
 * @returns {{
 *   get:(k:string)=>any, set:(k:string,v:any)=>void,
 *   subscribe:(fn:(k:string,v:any)=>void)=>()=>void, snapshot:()=>object
 * }}
 */
export function createParamState(overrides = {}) {
  const data = { ...DEFAULTS, ...overrides }
  const subs = new Set()

  return {
    get: (k) => data[k],
    set(k, v) {
      if (data[k] === v) return
      data[k] = v
      subs.forEach((fn) => fn(k, v))
    },
    subscribe(fn) {
      subs.add(fn)
      return () => subs.delete(fn)
    },
    snapshot: () => ({ ...data }),
  }
}
