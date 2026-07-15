/**
 * Photo mode — EffectComposer pipeline.
 *
 * Pipeline: RenderPass → [VolumetricInscatterPass] → SSAOPass → SMAAPass → [UnrealBloomPass] → OutputPass
 *
 * The VolumetricInscatterPass is always present in the chain but starts disabled;
 * orchestrator toggles `enabled` based on env-effect state and pushes per-frame
 * light uniforms via `inscatterPass.setLights(...)`.
 *
 * Default EffectComposer setup (no custom render target). The inscatter pass
 * owns its own depth pre-pass — see volumetric_inscatter_pass.js for why we
 * don't try to attach a DepthTexture to the main composer target.
 */

import * as THREE from 'three'
import { EffectComposer }   from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass }       from 'three/addons/postprocessing/RenderPass.js'
import { SSAOPass }         from 'three/addons/postprocessing/SSAOPass.js'
import { GTAOPass }         from 'three/addons/postprocessing/GTAOPass.js'
import { SMAAPass }         from 'three/addons/postprocessing/SMAAPass.js'
import { UnrealBloomPass }  from 'three/addons/postprocessing/UnrealBloomPass.js'
import { OutputPass }       from 'three/addons/postprocessing/OutputPass.js'
import { VolumetricInscatterPass } from './volumetric_inscatter_pass.js'
import { FigurePass }              from './figure_pass.js'

/**
 * @param {THREE.WebGLRenderer} renderer
 * @param {THREE.Scene}         scene
 * @param {THREE.Camera}        camera
 * @param {object}              opts
 * @param {boolean} [opts.ssao=true]
 * @param {boolean} [opts.ao=false]           — GTAO (occlusion shading)
 * @param {number}  [opts.aoRadius=2.0]       — nm
 * @param {number}  [opts.aoIntensity=1.0]
 * @param {boolean} [opts.bloom=false]
 * @param {number}  [opts.bloomStrength=0.5]
 * @param {number}  [opts.bloomRadius=0.4]
 * @param {number}  [opts.bloomThreshold=0.85]
 */
export function createComposer(renderer, scene, camera, opts = {}) {
  const {
    ssao          = true,
    ao            = false,
    aoRadius      = 2.0,
    aoIntensity   = 1.0,
    bloom         = false,
    bloomStrength = 0.5,
    bloomRadius   = 0.4,
    bloomThreshold = 0.85,
  } = opts

  const w = renderer.domElement.width
  const h = renderer.domElement.height

  // Default composer setup — no custom render target. The inscatter pass below
  // owns its own depth pre-pass (SSAOPass-style), so we don't have to attach
  // a DepthTexture here. This avoids an interaction that broke the surface
  // MeshPhysicalMaterial's transmission pre-pass on most drivers (see
  // memory/project_photo_mode.md "depth-texture format gotcha").
  const composer = new EffectComposer(renderer)

  // ── Render pass ──────────────────────────────────────────────────────────────
  const renderPass = new RenderPass(scene, camera)
  composer.addPass(renderPass)

  // ── Volumetric inscatter (mist + light shafts) ───────────────────────────────
  const inscatterPass = new VolumetricInscatterPass(scene, camera)
  inscatterPass.enabled = false   // toggled on by env-effect controller
  inscatterPass.setSize(w, h)     // size the depth pre-pass target before first render
  composer.addPass(inscatterPass)

  // ── SSAO ─────────────────────────────────────────────────────────────────────
  // Always constructed and present in the chain; `enabled` is toggled by the
  // setSSAO controller. Reconstructing the composer post-activate would put
  // the new UnrealBloomPass behind the renderer's already-mutated PMREM state
  // (see the env-bake note above) and re-trigger the bloom-writes-garbage bug.
  const ssaoPass = new SSAOPass(scene, camera, w, h)
  // Tuned for nm-scale DNA structures:
  // kernelRadius ≈ 0.3 nm — close-range occlusion between helices
  // minDistance  — avoid self-occlusion on flat surfaces
  // maxDistance  — don't darken wide open space
  ssaoPass.kernelRadius  = 0.3
  ssaoPass.minDistance   = 0.002
  ssaoPass.maxDistance   = 0.12
  ssaoPass.kernelSize    = 32
  ssaoPass.output        = SSAOPass.OUTPUT.Default
  ssaoPass.enabled       = !!ssao
  composer.addPass(ssaoPass)

  // ── GTAO — "occlusion shading" (the figure look) ─────────────────────────────
  // Ground-truth ambient occlusion, a much stronger and cleaner effect than the
  // SSAO garnish above. In the publication style this is the PRIMARY shading
  // cue: with flat materials and an ambient rig there is no key light, so the
  // crevices between helices are what conveys shape. Radius is in world units
  // (nm) — a couple of nm reaches between neighbouring helices in a bundle.
  // Always constructed, toggled via `enabled` (same rule as SSAO/Bloom: never
  // reconstruct the composer post-activate — see the note above).
  const gtaoPass = new GTAOPass(scene, camera, w, h)
  gtaoPass.output = GTAOPass.OUTPUT.Default   // AO multiplied into the beauty pass
  gtaoPass.blendIntensity = aoIntensity
  gtaoPass.updateGtaoMaterial({
    radius:           aoRadius,
    distanceExponent: 1.0,
    thickness:        1.0,
    scale:            1.0,
    samples:          16,
    screenSpaceRadius: false,   // radius is in nm, not pixels
  })
  gtaoPass.enabled = !!ao
  composer.addPass(gtaoPass)

  // ── Figure pass — silhouette outlines + depth cue ────────────────────────────
  // Placed AFTER the occlusion passes (so the contour is drawn over the shaded
  // image, not multiplied by AO) and BEFORE SMAA (so the contour gets
  // anti-aliased along with everything else — an un-AA'd 1 px outline is the
  // thing that makes a "toon" filter look cheap). Starts disabled; the
  // orchestrator enables it when outline and/or depth cue are on.
  const figurePass = new FigurePass(scene, camera)
  figurePass.enabled = false
  figurePass.setSize(w, h)
  composer.addPass(figurePass)

  // ── SMAA anti-aliasing ───────────────────────────────────────────────────────
  const smaaPass = new SMAAPass(w, h)
  composer.addPass(smaaPass)

  // ── Bloom — always allocated, toggled via .enabled (see SSAO note above) ────
  const bloomPass = new UnrealBloomPass(new THREE.Vector2(w, h), bloomStrength, bloomRadius, bloomThreshold)
  bloomPass.enabled = !!bloom
  composer.addPass(bloomPass)

  // ── Output (tone-mapping + colour-space correction) ───────────────────────────
  const outputPass = new OutputPass()
  composer.addPass(outputPass)

  // ── Handle ───────────────────────────────────────────────────────────────────

  function setSize(width, height) {
    composer.setSize(width, height)
    ssaoPass?.setSize(width, height)
    gtaoPass?.setSize(width, height)
    figurePass.setSize(width, height)
    inscatterPass.setSize(width, height)
  }

  function dispose() {
    inscatterPass.dispose()
    figurePass.dispose()
    gtaoPass.dispose?.()
    bloomPass.dispose?.()
    composer.dispose()
  }

  return { composer, ssaoPass, gtaoPass, figurePass, bloomPass, inscatterPass, setSize, dispose }
}
