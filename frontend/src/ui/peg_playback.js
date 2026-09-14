/** Frame indexing is display-only; MC steps are never converted to MD time. */
export function frameCoordinates(buffer, entry, index) {
  if (!(buffer instanceof Float32Array) || buffer.length !== entry.frames * entry.particles * 3 ||
      !Number.isInteger(index) || index < 0 || index >= entry.frames) throw new Error('Invalid recorded trajectory frame')
  const start = index * entry.particles * 3
  return buffer.subarray(start, start + entry.particles * 3)
}

export function frameLabel(entry, index) {
  const step = entry.steps[index]
  return entry.sampling === 'md'
    ? `${(step * entry.dtFs / 1e6).toFixed(3)} ns · step ${step.toLocaleString()}`
    : `${step.toLocaleString()} MC sweeps · no physical time mapping`
}
