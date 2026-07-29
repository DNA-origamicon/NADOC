/**
 * Photo mode — figure pass: silhouette outlines + depth cueing.
 *
 * This is the pass that makes a render read as a *molecular figure* (ChimeraX /
 * PyMOL house style) rather than a product render:
 *
 *   • Outline — a dark contour drawn at depth + normal discontinuities. This is
 *     what separates overlapping helices in a bundle without relying on
 *     lighting to do it, and it is the single largest contributor to the
 *     "publication" look.
 *   • Depth cue — a distance fade toward a flat colour, so the back of a thick
 *     bundle recedes instead of turning to visual mush.
 *
 * Both effects need scene depth + view-space normals, so they share ONE depth/
 * normal pre-pass and live in one pass. They remain INDEPENDENTLY toggleable
 * (`outline` / `depthCue`); the pass as a whole is skipped by EffectComposer
 * when both are off (the orchestrator sets `pass.enabled` accordingly).
 *
 * Pre-pass design follows volumetric_inscatter_pass.js: this pass owns its own
 * render target with an attached DepthTexture and renders the scene through an
 * overridden MeshNormalMaterial. We do NOT attach a DepthTexture to the
 * composer's main render target — that combination breaks the surface
 * MeshPhysicalMaterial's transmission shader on most drivers (see
 * memory/project_photo_mode.md "Depth-on-main-composer-target gotcha").
 *
 * Pre-pass exclusions (mirrors the material-swap skip-list in photo_renderer.js):
 * additive-blending sprites, line materials, and the shared-renderer LOD
 * impostors — the impostors compose their instance transforms in a custom
 * vertex shader that MeshNormalMaterial doesn't have, so under the override
 * they would collapse to the source origin and stamp a bogus edge there.
 */

import * as THREE from 'three'
import { Pass, FullScreenQuad } from 'three/addons/postprocessing/Pass.js'

// Raw depth at/above this is the far plane → background, not geometry.
const BACKGROUND_DEPTH = 0.9999

// Largest disc radius the ChimeraX-style min-filter will sample, in pixels.
// Fixed because GLSL ES 1.00 requires constant loop bounds; the thickness
// slider tops out at 4, and (2*4+1)^2 = 81 taps is already the cost ceiling
// for a full-screen pass at export resolution.
const MAX_DISC_R = 4

export const FigureShader = {
  uniforms: {
    tDiffuse:   { value: null },
    tNormal:    { value: null },
    tDepth:     { value: null },
    resolution: { value: new THREE.Vector2(1, 1) },
    cameraNear: { value: 0.1 },
    cameraFar:  { value: 2000 },

    // Outline
    uOutline:          { value: 0 },                       // 0/1
    uOutlineColor:     { value: new THREE.Color(0x1b1f24) },
    uOutlineStrength:  { value: 1.0 },                     // 0..1 opacity of the contour
    uOutlineThickness: { value: 1.4 },                     // px
    uDepthSens:        { value: 0.35 },                    // silhouette sensitivity (relative depth step)
    uNormalSens:       { value: 0.85 },                    // crease sensitivity (normal step)

    // Silhouette algorithm: 0 = Roberts cross on depth+normals (the original,
    // still what the shipping Photo tab uses), 1 = ChimeraX depth-outline.
    uSilhouette:  { value: 0 },
    uDepthJump:   { value: 0.03 },                         // ChimeraX depth_jump: fraction of scene depth
    uSceneDepth:  { value: 0 },                            // world-space depth span; <=0 falls back to far-near

    // Depth cue
    uCue:         { value: 0 },                            // 0/1
    uCueColor:    { value: new THREE.Color(0xffffff) },
    uCueStrength: { value: 0.45 },                         // 0..1 max fade at the far edge
    uCueNear:     { value: 1.0 },                          // eye-space distance where the fade starts
    uCueFar:      { value: 10.0 },                         // eye-space distance where the fade maxes out
  },

  vertexShader: /* glsl */`
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,

  fragmentShader: /* glsl */`
    #include <packing>

    uniform sampler2D tDiffuse;
    uniform sampler2D tNormal;
    uniform sampler2D tDepth;
    uniform vec2  resolution;
    uniform float cameraNear;
    uniform float cameraFar;

    uniform float uOutline;
    uniform vec3  uOutlineColor;
    uniform float uOutlineStrength;
    uniform float uOutlineThickness;
    uniform float uDepthSens;
    uniform float uNormalSens;
    uniform float uSilhouette;
    uniform float uDepthJump;
    uniform float uSceneDepth;

    uniform float uCue;
    uniform vec3  uCueColor;
    uniform float uCueStrength;
    uniform float uCueNear;
    uniform float uCueFar;

    varying vec2 vUv;

    float rawDepth(vec2 uv) {
      return texture2D(tDepth, uv).x;
    }

    // Eye-space distance from the camera (positive, in world units = nm).
    float eyeDepth(vec2 uv) {
      float d = rawDepth(uv);
      if (d >= ${BACKGROUND_DEPTH}) return cameraFar;
      #if PERSPECTIVE_CAMERA == 1
        return -perspectiveDepthToViewZ(d, cameraNear, cameraFar);
      #else
        return -orthographicDepthToViewZ(d, cameraNear, cameraFar);
      #endif
    }

    vec3 viewNormal(vec2 uv) {
      return normalize(texture2D(tNormal, uv).rgb * 2.0 - 1.0);
    }

    void main() {
      vec4 diffuse = texture2D(tDiffuse, vUv);
      float dCenter = rawDepth(vUv);
      bool  isBackground = dCenter >= ${BACKGROUND_DEPTH};

      // In Roberts mode background pixels are left completely untouched — no
      // contour, no cue. That is what keeps a transparent-background export
      // transparent: the silhouette is drawn just INSIDE the object.
      // The ChimeraX mode deliberately DOES paint background pixels (see below),
      // so it only short-circuits the cue.
      if (isBackground && !(uOutline > 0.5 && uSilhouette > 0.5)) {
        gl_FragColor = diffuse;
        return;
      }

      vec3  color = diffuse.rgb;
      float alpha = diffuse.a;
      float eye   = eyeDepth(vUv);

      // ── Depth cue ─────────────────────────────────────────────────────────
      // Linear fade toward uCueColor between uCueNear and uCueFar (both pushed
      // per-frame by the orchestrator from the scene bbox, so the window tracks
      // the structure's own depth rather than the camera's absolute distance —
      // this is what keeps it working at any FOV, including the near-parallel
      // long-lens projection where camera distance balloons).
      if (uCue > 0.5 && !isBackground) {
        float t = clamp((eye - uCueNear) / max(uCueFar - uCueNear, 1e-4), 0.0, 1.0);
        color = mix(color, uCueColor, t * uCueStrength);
      }

      // ── Outline ───────────────────────────────────────────────────────────
      if (uOutline > 0.5) {
        float edge = 0.0;

        if (uSilhouette > 0.5) {
          // ChimeraX depth-outline (graphics/opengl.py Silhouette +
          // fragmentShader.txt USE_DEPTH_OUTLINE). Depth ONLY — no normals, so
          // it never turns a field of beads into line-art the way a crease term
          // does at low zoom.
          //
          // Take the MINIMUM depth over a circular disc of radius = thickness
          // and draw where the centre pixel is FARTHER than that minimum. The
          // contour therefore lands on the surface BEHIND the edge (including
          // empty background), leaving the near object's silhouette intact
          // rather than eroding it.
          //
          // ChimeraX's test  nf*(d0-ds) < jump*(1-nf1*ds)*(1-nf1*d0)  is a
          // perspective linearization of the depth buffer; it reduces exactly to
          //     Δz_eye  >=  depth_jump * (far - near)
          // i.e. one constant WORLD-space gap everywhere in the frame. We already
          // hold linear eye depth, so we apply that form directly — and use the
          // structure's own depth span (pushed from the scene bbox) instead of
          // the camera's far-near, which is far looser than ChimeraX's per-frame
          // bbox-fitted clip planes.
          float dsEye = eye;
          float r2 = uOutlineThickness * uOutlineThickness;
          for (int i = -${MAX_DISC_R}; i <= ${MAX_DISC_R}; ++i) {
            for (int j = -${MAX_DISC_R}; j <= ${MAX_DISC_R}; ++j) {
              float rr = float(i * i + j * j);
              if (rr < 0.5 || rr > r2) continue;   // skip centre + outside disc
              dsEye = min(dsEye, eyeDepth(vUv + vec2(float(i), float(j)) / resolution));
            }
          }
          float span   = uSceneDepth > 0.0 ? uSceneDepth : max(cameraFar - cameraNear, 1e-4);
          float thresh = max(uDepthJump * span, 1e-5);
          // ChimeraX hard-discards and leans on supersampling for AA; the
          // smoothstep costs nothing and gives a clean edge in the live preview.
          edge = smoothstep(thresh, thresh * 2.0, eye - dsEye) * uOutlineStrength;
        } else {
          // Roberts cross on BOTH linearized depth and view-space normals:
          //  - the depth term catches silhouettes (one surface in front of another)
          //  - the normal term catches creases (a sharp fold within one surface)
          // Depth differences are normalized by the centre depth so a contour on a
          // distant helix is as strong as one on a near helix.
          vec2 o = uOutlineThickness / resolution;

          float da = eyeDepth(vUv + vec2( o.x,  o.y));
          float db = eyeDepth(vUv + vec2(-o.x, -o.y));
          float dc = eyeDepth(vUv + vec2( o.x, -o.y));
          float dd = eyeDepth(vUv + vec2(-o.x,  o.y));
          float depthDiff = length(vec2(da - db, dc - dd)) / max(eye, 1e-3);

          vec3 na = viewNormal(vUv + vec2( o.x,  o.y));
          vec3 nb = viewNormal(vUv + vec2(-o.x, -o.y));
          vec3 nc = viewNormal(vUv + vec2( o.x, -o.y));
          vec3 nd = viewNormal(vUv + vec2(-o.x,  o.y));
          float normalDiff = length(na - nb) + length(nc - nd);

          float edgeD = smoothstep(uDepthSens  * 0.5, uDepthSens,  depthDiff);
          float edgeN = smoothstep(uNormalSens * 0.5, uNormalSens, normalDiff);
          edge = max(edgeD, edgeN) * uOutlineStrength;
        }

        edge  = clamp(edge, 0.0, 1.0);
        color = mix(color, uOutlineColor, edge);
        // A contour painted onto transparent background must become visible, or
        // an alpha export would drop the very line we just drew.
        alpha = max(alpha, edge);
      }

      gl_FragColor = vec4(color, alpha);
    }
  `,
}

export class FigurePass extends Pass {
  /**
   * @param {THREE.Scene}  scene
   * @param {THREE.Camera} camera
   */
  constructor(scene, camera) {
    super()
    this.scene  = scene
    this.camera = camera

    this.needsSwap = true

    // Depth + view-space-normal pre-pass target. DepthStencilFormat +
    // UnsignedInt248Type is the driver-safe combination (the SSAOPass one);
    // plain DepthFormat + UnsignedIntType breaks the transmission shader.
    this._prepassRT = new THREE.WebGLRenderTarget(1, 1, {
      minFilter: THREE.NearestFilter,
      magFilter: THREE.NearestFilter,
      type: THREE.UnsignedByteType,
    })
    this._prepassRT.depthTexture = new THREE.DepthTexture(1, 1)
    this._prepassRT.depthTexture.format = THREE.DepthStencilFormat
    this._prepassRT.depthTexture.type   = THREE.UnsignedInt248Type

    this._normalMaterial = new THREE.MeshNormalMaterial()

    this._material = new THREE.ShaderMaterial({
      defines:       { PERSPECTIVE_CAMERA: camera.isOrthographicCamera ? 0 : 1 },
      uniforms:      THREE.UniformsUtils.clone(FigureShader.uniforms),
      vertexShader:   FigureShader.vertexShader,
      fragmentShader: FigureShader.fragmentShader,
    })
    this._fsQuad = new FullScreenQuad(this._material)

    // Meshes hidden for the duration of the pre-pass, restored right after.
    this._hidden = []
  }

  get uniforms() { return this._material.uniforms }

  /**
   * Push the orchestrator's settings into the shader uniforms.
   * Anything omitted is left at its current value.
   */
  setParams(p = {}) {
    const u = this._material.uniforms
    if (p.outline          !== undefined) u.uOutline.value          = p.outline ? 1 : 0
    if (p.outlineColor     !== undefined) u.uOutlineColor.value.set(p.outlineColor)
    if (p.outlineStrength  !== undefined) u.uOutlineStrength.value  = p.outlineStrength
    if (p.outlineThickness !== undefined) u.uOutlineThickness.value = p.outlineThickness
    if (p.outlineDepthSensitivity  !== undefined) u.uDepthSens.value  = p.outlineDepthSensitivity
    if (p.outlineCreaseSensitivity !== undefined) u.uNormalSens.value = p.outlineCreaseSensitivity
    if (p.silhouette   !== undefined) u.uSilhouette.value = p.silhouette === 'chimerax' ? 1 : 0
    if (p.outlineDepthJump !== undefined) u.uDepthJump.value = p.outlineDepthJump
    if (p.depthCue         !== undefined) u.uCue.value          = p.depthCue ? 1 : 0
    if (p.depthCueColor    !== undefined) u.uCueColor.value.set(p.depthCueColor)
    if (p.depthCueStrength !== undefined) u.uCueStrength.value  = p.depthCueStrength
  }

  /**
   * Depth-cue window, in eye-space distance from the camera (nm).
   * Pushed per-frame by the orchestrator from the scene bounding box, so the
   * fade always spans the structure's own depth.
   */
  setCueRange(near, far) {
    const u = this._material.uniforms
    u.uCueNear.value = near
    u.uCueFar.value  = Math.max(far, near + 1e-4)
  }

  /**
   * World-space depth span of the structure, in nm — the denominator ChimeraX's
   * `depth_jump` is a fraction OF. ChimeraX gets this for free because it refits
   * the clip planes to the scene bbox every frame; we don't, so the orchestrator
   * pushes the bbox diagonal here. 0 falls back to (far - near).
   */
  setSceneDepth(span) {
    this._material.uniforms.uSceneDepth.value = span > 0 ? span : 0
  }

  /** True when this pass would change any pixel — used to drive `enabled`. */
  hasEffect() {
    const u = this._material.uniforms
    return u.uOutline.value > 0.5 || u.uCue.value > 0.5
  }

  // Hide objects whose geometry the MeshNormalMaterial override cannot
  // reproduce (custom instancing shaders) or that shouldn't contribute edges
  // (additive glow sprites, helper lines).
  _hideNonSurfaces() {
    this._hidden.length = 0
    this.scene.traverse(obj => {
      if ((!obj.isMesh && !obj.isInstancedMesh) || !obj.visible) return
      const m = obj.material
      const skip = obj.userData?.sharedLodImpostor
        || m?.isLineBasicMaterial
        || m?.isLineDashedMaterial
        || m?.blending === THREE.AdditiveBlending
      if (skip) {
        obj.visible = false
        this._hidden.push(obj)
      }
    })
  }

  _restoreHidden() {
    for (const obj of this._hidden) obj.visible = true
    this._hidden.length = 0
  }

  render(renderer, writeBuffer, readBuffer /* , deltaTime, maskActive */) {
    const u = this._material.uniforms

    // ── Depth + normal pre-pass ────────────────────────────────────────────
    const prevRT       = renderer.getRenderTarget()
    const prevOverride = this.scene.overrideMaterial
    const prevBg       = this.scene.background

    this._hideNonSurfaces()
    this.scene.overrideMaterial = this._normalMaterial
    this.scene.background       = null
    renderer.setRenderTarget(this._prepassRT)
    renderer.clear(true, true, false)
    renderer.render(this.scene, this.camera)
    this.scene.overrideMaterial = prevOverride
    this.scene.background       = prevBg
    this._restoreHidden()
    renderer.setRenderTarget(prevRT)

    // ── Composite ──────────────────────────────────────────────────────────
    u.tDiffuse.value   = readBuffer.texture
    u.tNormal.value    = this._prepassRT.texture
    u.tDepth.value     = this._prepassRT.depthTexture
    u.cameraNear.value = this.camera.near
    u.cameraFar.value  = this.camera.far

    // A camera swapped after construction (or an ortho export camera) must
    // re-pick the depth linearization branch.
    const wantPerspective = this.camera.isOrthographicCamera ? 0 : 1
    if (this._material.defines.PERSPECTIVE_CAMERA !== wantPerspective) {
      this._material.defines.PERSPECTIVE_CAMERA = wantPerspective
      this._material.needsUpdate = true
    }

    if (this.renderToScreen) {
      renderer.setRenderTarget(null)
    } else {
      renderer.setRenderTarget(writeBuffer)
      if (this.clear) renderer.clear()
    }
    this._fsQuad.render(renderer)
  }

  setSize(width, height) {
    this._prepassRT.setSize(width, height)
    this._material.uniforms.resolution.value.set(width, height)
  }

  dispose() {
    this._prepassRT.depthTexture?.dispose()
    this._prepassRT.dispose()
    this._normalMaterial.dispose()
    this._material.dispose()
    this._fsQuad.dispose()
  }
}
