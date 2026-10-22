import * as THREE from 'three'
import shared from '../../../native/vr_viewer/src/annotation_glyph_shader.inc?raw'

// One distance-field formula for desktop and native VR. The plane includes the
// soft halo; glyph centres are still the exact molecular annotation positions.
const shader = shared.slice(shared.indexOf('(') + 1, shared.lastIndexOf(')GLSL"'))
export const GLYPH_SIZE = 1.2
export const GLYPH_MIN_PIXELS = 18
const glyphCompilers = new WeakMap()
export const loopSkipGlyphKind = compiler => glyphCompilers.get(compiler)
export function loopSkipGlyphMaterial(kind, color) {
  const material = new THREE.MeshBasicMaterial({color,transparent:true,depthTest:false,depthWrite:false,side:THREE.DoubleSide,toneMapped:false})
  return applyLoopSkipGlyphMaterial(material,kind)
}
export function applyLoopSkipGlyphMaterial(material,kind) {
  const viewport = new THREE.Vector2(1,1)
  material.userData.glyphViewport = viewport
  material.customProgramCacheKey = () => `loop-skip-glow-${kind}`
  material.onBeforeCompile = program => {
    program.uniforms.glyphViewport = {value:viewport}
    program.vertexShader = 'uniform vec2 glyphViewport; varying vec2 glyphPosition;\n' + program.vertexShader
    program.vertexShader = program.vertexShader.replace('#include <project_vertex>', `
      glyphPosition=position.xy/${GLYPH_SIZE.toFixed(1)};
      vec4 centre=modelViewMatrix*vec4(0.0,0.0,0.0,1.0);
      float size=length(modelMatrix[0].xyz);
      vec4 projected=projectionMatrix*centre;
      float pixels=abs(projectionMatrix[0][0]*${GLYPH_SIZE.toFixed(1)}*size/projected.w)*glyphViewport.x*0.5;
      float expand=max(1.0,${GLYPH_MIN_PIXELS.toFixed(1)}/max(pixels,0.001));
      vec4 mvPosition=centre+vec4(position.xy*size*expand,0.0,0.0);
      gl_Position=projectionMatrix*mvPosition;`)
    program.fragmentShader = 'varying vec2 glyphPosition;\n' + shader + program.fragmentShader
    program.fragmentShader = program.fragmentShader.replace('#include <color_fragment>', `
      vec4 glyph=annotationGlyph(glyphPosition,${kind==='loop'?'3.0':'4.0'},diffuseColor.rgb);
      diffuseColor=vec4(glyph.rgb,diffuseColor.a*glyph.a);
      if(diffuseColor.a<0.01)discard;`)
  }
  glyphCompilers.set(material.onBeforeCompile,kind)
  return material
}
export function configureLoopSkipGlyph(mesh,kind) {
  mesh.userData.vrAnnotation=true
  mesh.userData.vrGlyph=kind
  mesh.frustumCulled=false // minimum screen extent can exceed the local plane bounds
  mesh.onBeforeRender=renderer=>renderer.getDrawingBufferSize(mesh.material.userData.glyphViewport)
  return mesh
}
