/**
 * Generic numeric-array helpers extracted from main.js. Pure (Math only).
 * Unit-tested in vec_math.test.js.
 */

/** True if two numeric arrays are the same length and elementwise within eps. */
export function vecClose(a = [], b = [], eps = 1e-6) {
  return a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) <= eps)
}
