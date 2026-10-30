/** Selection-only version of the photomode circular minimum-depth outline.
 * Keep the source materials: atom impostors write curved fragment depth and
 * discard the corners of their quads. A normal-material override loses both.
 */
import * as THREE from 'three'
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js'

const providers = new WeakMap()
export function registerSilhouetteHighlights(scene, provider) {
  providers.set(scene, provider)
  return () => { if (providers.get(scene) === provider) providers.delete(scene) }
}
export function renderSilhouetteHighlights(renderer, scene, camera, pixelScale = 1) {
  providers.get(scene)?.(renderer, camera, pixelScale)
}

function visibleSurface(mesh) {
  if (!mesh?.isMesh) return false
  let attached = false
  for (let obj = mesh; obj; obj = obj.parent) {
    if (!obj.visible) return false
    if (obj.isScene) attached = true
  }
  if (!attached) return false
  const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
  return materials.some(m => m?.visible && m.depthWrite && !(m.transparent && m.opacity === 0))
}

export class SilhouetteHighlight {
  constructor() {
    this.scene = new THREE.Scene()
    this.proxies = new Map()
    this.target = new THREE.WebGLRenderTarget(1, 1, { depthTexture: new THREE.DepthTexture(1, 1) })
    this.material = new THREE.ShaderMaterial({
      transparent: true, depthTest: false, depthWrite: false,
      uniforms: { depth: { value: this.target.depthTexture }, resolution: { value: new THREE.Vector2() },
        near: { value: 0.1 }, far: { value: 1000 }, perspective: { value: 1 },
        pixelScale: { value: 1 }, jump: { value: 0.03 }, color: { value: new THREE.Color() }, strength: { value: 1 } },
      vertexShader: 'varying vec2 uvOut; void main(){ uvOut=uv; gl_Position=vec4(position.xy,0.,1.); }',
      fragmentShader: `
        #include <packing>
        uniform sampler2D depth;
        uniform vec2 resolution;
        uniform float near, far, perspective, jump, strength, pixelScale;
        uniform vec3 color;
        varying vec2 uvOut;
        float eye(vec2 uv) {
          float d = texture2D(depth, clamp(uv, vec2(0.), vec2(1.))).x;
          return perspective > .5 ? -perspectiveDepthToViewZ(d, near, far) : -orthographicDepthToViewZ(d, near, far);
        }
        void main() {
          float center = eye(uvOut), closest = center;
          // Same circular minimum-depth filter and world-space jump as FigurePass.
          for (int x=-2; x<=2; x++) for (int y=-2; y<=2; y++) {
            if (x*x+y*y > 4) continue;
            closest = min(closest, eye(uvOut + vec2(float(x),float(y))*pixelScale/resolution));
          }
          float edge = smoothstep(jump, jump*2., center-closest);
          gl_FragColor = vec4(color, edge * min(strength, 1.));
          #include <colorspace_fragment>
        }`,
    })
    this.quad = new FullScreenQuad(this.material)
  }

  render(renderer, camera, entries, color, intensity, pixelScale = 1) {
    if (!intensity) return
    const groups = new Map()
    for (const entry of entries) {
      const source = entry.instMesh ?? entry.mesh
      if (!visibleSurface(source)) continue
      if (!groups.has(source)) groups.set(source, new Set())
      if (entry.instMesh) groups.get(source).add(entry.id)
    }
    if (!groups.size) return
    const bounds = new THREE.Box3(), matrix = new THREE.Matrix4(), point = new THREE.Vector3()
    for (const [source, proxy] of this.proxies) {
      if (!groups.has(source) || proxy.geometry !== source.geometry || proxy.count !== source.count) {
        this.scene.remove(proxy); proxy.dispose?.(); this.proxies.delete(source)
      }
    }
    for (const [source, ids] of groups) {
      source.updateWorldMatrix(true, false)
      let proxy = this.proxies.get(source)
      if (!proxy) {
        // Do not clone userData: nanoparticle metadata can hold renderer objects
        // and circular scene references. Only the drawable surface is needed.
        proxy = source.isInstancedMesh
          ? new THREE.InstancedMesh(source.geometry, source.material, source.instanceMatrix.count)
          : new THREE.Mesh(source.geometry, source.material)
        if (source.isInstancedMesh) proxy.count = source.count
        proxy.matrixAutoUpdate = false
        proxy.frustumCulled = false
        this.proxies.set(source, proxy); this.scene.add(proxy)
      }
      proxy.material = source.material
      proxy.layers.mask = source.layers.mask
      proxy.onBeforeRender = (...args) => source.onBeforeRender(...args)
      proxy.matrix.copy(source.matrixWorld)
      proxy.matrixWorldNeedsUpdate = true
      if (source.isInstancedMesh) {
        // Keep indices stable for geometry-owned per-instance alpha attributes.
        proxy.instanceMatrix.array.fill(0)
        for (const id of ids) {
          source.getMatrixAt(id, matrix)
          proxy.setMatrixAt(id, matrix)
          point.setFromMatrixPosition(matrix).applyMatrix4(source.matrixWorld)
          bounds.expandByPoint(point)
        }
        proxy.instanceMatrix.needsUpdate = true
        proxy.instanceColor = source.instanceColor
      } else bounds.union(new THREE.Box3().setFromObject(source))
    }
    const size = renderer.getDrawingBufferSize(new THREE.Vector2())
    this.target.setSize(size.x, size.y)
    const u = this.material.uniforms
    u.resolution.value.copy(size); u.near.value = camera.near; u.far.value = camera.far
    u.perspective.value = camera.isPerspectiveCamera ? 1 : 0
    u.jump.value = Math.max(bounds.getSize(point).length() * 0.03, 0.003)
    u.color.value.set(color); u.strength.value = intensity
    u.pixelScale.value = pixelScale
    const oldTarget = renderer.getRenderTarget(), oldAuto = renderer.autoClear
    const oldColor = renderer.getClearColor(new THREE.Color()), oldAlpha = renderer.getClearAlpha()
    const oldShadow = renderer.shadowMap.autoUpdate
    try {
      renderer.shadowMap.autoUpdate = false
      renderer.autoClear = true
      renderer.setClearColor(0, 0)
      renderer.setRenderTarget(this.target)
      renderer.render(this.scene, camera)
      renderer.setRenderTarget(oldTarget)
      renderer.autoClear = false
      this.quad.render(renderer)
    } finally {
      renderer.setRenderTarget(oldTarget)
      renderer.autoClear = oldAuto
      renderer.setClearColor(oldColor, oldAlpha)
      renderer.shadowMap.autoUpdate = oldShadow
    }
  }
  dispose() {
    for (const proxy of this.proxies.values()) proxy.dispose?.()
    this.proxies.clear(); this.target.dispose(); this.material.dispose(); this.quad.dispose()
  }
}
