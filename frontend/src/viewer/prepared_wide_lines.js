import { LineMaterial } from 'three/addons/lines/LineMaterial.js'
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js'

const PROPERTIES = ['linewidth', 'worldUnits', 'dashed', 'dashScale', 'dashSize', 'gapSize', 'dashOffset', 'alphaToCoverage', 'vertexColors', 'opacity', 'transparent', 'depthTest', 'depthWrite', 'side', 'toneMapped']
/** Package data, never shader source or arbitrary uniforms. The guest owns the shader. */
export function encodeWideLineMaterial(material) {
  return { uuid: material.uuid, type: 'LineBasicMaterial', wideLine: true,
    ...Object.fromEntries(PROPERTIES.map(key => [key, material[key]])) }
}
export function validateWideLineMaterial(material) {
  if (!material.wideLine) return
  if (material.type !== 'LineBasicMaterial' || !Number.isFinite(material.linewidth) || material.linewidth <= 0 || material.linewidth > 1000) throw new Error('Invalid wide-line material')
  for (const key of PROPERTIES) {
    const value = material[key]
    if (typeof value !== 'boolean' && (typeof value !== 'number' || !Number.isFinite(value))) throw new Error('Invalid wide-line setting')
  }
}
export function loadWideLineMaterial(material) {
  return new LineMaterial(Object.fromEntries(PROPERTIES.map(key => [key, material[key]])))
}
export function restoreWideLine(object) {
  const line = new LineSegments2(object.geometry, object.material)
  line.copy(object, false); line.uuid = object.uuid
  line.children = object.children
  for (const child of line.children) child.parent = line
  return line
}
