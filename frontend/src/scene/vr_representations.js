/** Desktop representation IDs accepted by the native companion. */
export const VR_REPRESENTATIONS = Object.freeze([
  'cylinders', 'full', 'ballstick', 'stick', 'beads', 'vdw', 'hull-prism',
  'surface', 'mrdna-coarse', 'mrdna-fine', 'oxdna',
])
export const nativeRepresentation = value => VR_REPRESENTATIONS.includes(value) ? value : 'full'
