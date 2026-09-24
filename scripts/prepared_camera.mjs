/** Validate and copy data-only camera poses for both live and one-shot sharing. */
export function validateSharedCamera(c) {
  const vector = a => Array.isArray(a) && a.length === 3 && a.every(x => Number.isFinite(x) && Math.abs(x) <= 1e9)
  if (!c || !['position', 'target', 'up'].every(k => vector(c[k])) || Math.hypot(...c.up) < .001 ||
    Math.hypot(...c.position.map((v, i) => v - c.target[i])) < .000001 ||
    !Number.isFinite(c.fov) || c.fov < 1 || c.fov > 175 || !Number.isFinite(c.near) || c.near <= 0 ||
    !Number.isFinite(c.far) || c.far <= c.near || c.far > 1e12 || !['orbit', 'trackball', 'multiscale'].includes(c.orbitMode)) throw new Error('Invalid presenter camera')
  return { position: [...c.position], target: [...c.target], up: [...c.up], fov: c.fov, near: c.near, far: c.far, orbitMode: c.orbitMode }
}
