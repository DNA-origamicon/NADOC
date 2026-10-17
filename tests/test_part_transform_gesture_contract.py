"""Actual native gizmo drafts cross back into owned compound-pose Apply.

No browser, GPU, archive fixture, fake pending pose, or production file output.
Node receives the real host packet, renders it privately, and drives the existing
TransformControls event path or the actual joint-ring pointer handler.
"""

import json
from pathlib import Path
import subprocess

import pytest

from backend.api import part_deformation_preview_sessions as host, state
from backend.core import models as m
from tests.test_part_deformation_preview_sessions import cancellation, checkpoint, unchanged
from tests.test_part_transform_constraint_history import constraint_recipe
from tests.test_part_transform_preview import FEATURE
from tests.test_part_transform_preview_sessions import document, opening, update, verified  # noqa: F401


SCRIPT = r"""
import { JSDOM } from './frontend/node_modules/jsdom/lib/api.js';
import * as THREE from './frontend/node_modules/three/build/three.module.js';
import { BroadcastChannel as NativeBroadcastChannel } from 'node:worker_threads';
const dom = new JSDOM('<!doctype html><html><body><canvas></canvas></body></html>', {
  pretendToBeVisual: true, url: 'http://localhost/?doc=__native_transform_gesture__',
});
for (const key of ['window','document','location','history','localStorage','sessionStorage','navigator',
  'HTMLElement','HTMLCanvasElement','Element','Event','CustomEvent','MouseEvent','KeyboardEvent','DOMException'])
  Object.defineProperty(globalThis, key, { value: key === 'window' ? dom.window : dom.window[key], configurable: true });
globalThis.requestAnimationFrame = dom.window.requestAnimationFrame.bind(dom.window);
globalThis.cancelAnimationFrame = dom.window.cancelAnimationFrame.bind(dom.window);
globalThis.getComputedStyle = dom.window.getComputedStyle.bind(dom.window);
const channels = [];
let networkCalls = 0, broadcastCalls = 0;
globalThis.fetch = async () => { networkCalls++; throw new Error('Network request during private gesture'); };
globalThis.BroadcastChannel = class extends NativeBroadcastChannel {
  constructor(...args) { super(...args); channels.push(this); }
  postMessage() { broadcastCalls++; throw new Error('Canonical broadcast during private gesture'); }
};
const { validateTransformPreviewDisplay } = await import('./frontend/src/features/transform_preview_display.js');
const { createTransformHistoryPreview } = await import('./frontend/src/scene/transform_history_preview.js');
const { createTransformHistoryTool } = await import('./frontend/src/scene/transform_history_tool.js');
const { initClusterGizmo } = await import('./frontend/src/scene/cluster_gizmo.js');
const { store } = await import('./frontend/src/state/store.js');
let raw = ''; for await (const chunk of process.stdin) raw += chunk;
const { packet, gesture, ids, cancel = false, joint_limit = 25 } = JSON.parse(raw), original = JSON.stringify(packet);
validateTransformPreviewDisplay(packet, { prepare: true, requireEnvelope: true });
store.getState = () => { throw new Error('Canonical store read during private gesture'); };
store.setState = () => { throw new Error('Canonical mutation during private gesture'); };
const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(50, 1, .01, 10000);
camera.position.set(0, 0, 40); camera.lookAt(0, 0, 0); camera.updateMatrixWorld(true);
const canvas = document.querySelector('canvas');
canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 800 });
canvas.setPointerCapture = () => {}; canvas.releasePointerCapture = () => {};
const controls = { enabled: false }, preview = createTransformHistoryPreview({ scene, camera });
let callbacks, gizmo, tool, cancelled = false, applied = 0, released = 0;
const drafts = [], errors = [];
const panel = { bindHistorySession(value) { callbacks = value; return {
  update() {}, setStatus() {}, release() { released++; },
}; } };
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const pose = value => ({ cluster_id: value.clusterId, translation: value.translation, rotation: value.rotation, pivot: value.pivot });
const primary = packet.control_context.inputs.primary_cluster_id ?? packet.control_context.inputs.cluster_id;
const definition = draft => draft.definition ?? draft;
let initialDrafts = 0;
let result, constraintEvidence = null, jointError = null, rootPivot = null;
try {
  preview.open(packet);
  tool = createTransformHistoryTool({ scene, camera, canvas, controls, panel, preview,
    createClusterGizmo: (...args) => (gizmo = initClusterGizmo(...args)),
    onChange: draft => drafts.push(structuredClone(draft)), onReset() {}, onApply() { applied++; },
    onCancel() { cancelled = true; tool.dispose(); }, onError: error => errors.push(error.message) });
  tool.open(packet);
  if (packet.command_kind === 'cluster_op') {
    callbacks.onUpgrade(); await tick();
    const descriptor = packet.control_context.placement_upgrade;
    if (!descriptor || drafts.length !== 1 || Object.entries(descriptor).some(([key, value]) => drafts[0][key] !== value))
      throw new Error('Native explicit upgrade did not retain the original definition guard');
    initialDrafts = drafts.length;
  }
  const nativeGeometry = preview.candidateGeometry();
  const nativeAnchor = anchor => {
    const value = nativeGeometry.backboneEntries.find(entry => entry.nuc.helix_id === anchor.helix_id
      && entry.nuc.bp_index === anchor.bp && entry.nuc.direction === anchor.direction);
    if (!value) throw new Error('Native constraint anchor is absent from the rendered owned prefix');
    return value.pos.clone();
  };
  if (gesture === 'joint') {
    callbacks.onPivot(ids.joint);
    const joint = packet.control_state.cluster_joints.find(value => value.id === ids.joint);
    const origin = new THREE.Vector3(...joint.axis_origin), axis = new THREE.Vector3(...joint.axis_direction).normalize();
    const u = axis.clone().cross(Math.abs(axis.z) < .9 ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(0, 1, 0)).normalize();
    const v = axis.clone().cross(u).normalize();
    camera.position.copy(origin).addScaledVector(axis, 40); camera.up.copy(v); camera.lookAt(origin); camera.updateMatrixWorld(true);
    const ring = scene.children.find(node => node.geometry?.type === 'TorusGeometry');
    if (!ring) throw new Error('Actual native joint ring was not created');
    const baseline = packet.control_state.cluster_transforms.find(owner => owner.id === primary);
    if (baseline.parent_cluster_id !== null || joint.max_angle_deg !== joint_limit || !(joint_limit > 0 && joint_limit < 90))
      throw new Error('The independent joint oracle requires the exact historical limit and a root placement');
    const baseQ = new THREE.Quaternion(...baseline.rotation);
    const proposedQ = new THREE.Quaternion().setFromAxisAngle(axis, Math.PI / 2).multiply(baseQ);
    // Expected orientation: preserve the requested swing and bound its twist.
    // The separate world-point oracle below checks pivot and translation as well.
    const axial = new THREE.Vector3(proposedQ.x, proposedQ.y, proposedQ.z).dot(axis);
    let proposedAngle = 2 * Math.atan2(axial, proposedQ.w);
    while (proposedAngle > Math.PI) proposedAngle -= 2 * Math.PI;
    while (proposedAngle <= -Math.PI) proposedAngle += 2 * Math.PI;
    const boundedAngle = Math.max(joint.min_angle_deg * Math.PI / 180,
      Math.min(joint.max_angle_deg * Math.PI / 180, proposedAngle));
    if (Math.abs(boundedAngle - proposedAngle) < 1e-3)
      throw new Error('Joint fixture did not exercise its historical angular limit');
    const expectedQ = proposedQ.clone().multiply(new THREE.Quaternion().setFromAxisAngle(axis, boundedAngle - proposedAngle));
    const worldDelta = expectedQ.clone().multiply(baseQ.clone().invert());
    const probes = nativeGeometry.backboneEntries.filter(entry => baseline.helix_ids.includes(entry.nuc.helix_id));
    if (probes.length < 2) throw new Error('Native joint oracle needs two real backbone probes');
    const worldError = draft => {
      const written = definition(draft).poses.find(owner => owner.cluster_id === primary);
      if (new THREE.Quaternion(...written.rotation).angleTo(expectedQ) > 1e-7)
        throw new Error('Joint draft lost the expected bounded orientation');
      return Math.max(...[probes[0], probes.at(-1)].map(entry => {
        const expected = entry.pos.clone().sub(origin).applyQuaternion(worldDelta).add(origin);
        // Independent original-world -> stored-rest -> authored-world check.
        const actual = entry.pos.clone().sub(new THREE.Vector3(...baseline.translation))
          .sub(new THREE.Vector3(...baseline.pivot)).applyQuaternion(new THREE.Quaternion(...baseline.rotation).invert())
          .add(new THREE.Vector3(...baseline.pivot)).sub(new THREE.Vector3(...written.pivot))
          .applyQuaternion(new THREE.Quaternion(...written.rotation)).add(new THREE.Vector3(...written.pivot))
          .add(new THREE.Vector3(...written.translation));
        return actual.distanceTo(expected);
      }));
    };
    const r = ring.geometry.parameters.radius;
    const pointer = (type, direction) => {
      const position = ring.position.clone().addScaledVector(direction, r).project(camera);
      canvas.dispatchEvent(new dom.window.MouseEvent(type, { bubbles: true, button: 0,
        clientX: (position.x + 1) * 400, clientY: (1 - position.y) * 400 }));
    };
    pointer('pointerdown', u);
    if (!gizmo.isDragging()) throw new Error('Joint pointer did not enter the native ring gesture');
    pointer('pointermove', v); await tick();
    const intermediateError = worldError(drafts.at(-1));
    pointer('pointerup', v); await tick();
    jointError = Math.max(intermediateError, worldError(drafts.at(-1)));
    if (jointError > 1e-8) throw new Error('Native joint draft did not preserve the historical axis rotation before and after release');
  } else {
    callbacks.onPivot(gesture === 'free' ? 'centroid' : gesture === 'duplex-root' ? `dup:root:${ids.driver}`
      : gesture === 'duplex-taut' ? 'dup:taut' : 'ssdna');
    await tick();
    if (gesture === 'duplex-root') {
      const owner = packet.control_state.cluster_transforms.find(value => value.id === primary);
      rootPivot = packet.control_state.placement_constraints.find(value => value.cluster_id === primary)
        ?.rotation_points.find(value => value.kind === 'overhang_root' && value.overhang_id === ids.driver)?.point;
      if (owner.overhang_duplex_driver_id !== ids.driver || !rootPivot || JSON.stringify(gizmo.getPivot()) !== JSON.stringify(rootPivot))
        throw new Error('Duplex gesture did not select the exact native driver root pivot');
    }
    const tc = scene.children.find(node => node.controls)?.controls;
    if (!tc?.object) throw new Error('Actual native TransformControls was not attached');
    let delta = new THREE.Vector3(-1, 1, .25);
    if (['flexible', 'ss-linker', 'ds-linker', 'duplex-taut'].includes(gesture)) {
      let tether;
      if (gesture === 'flexible') {
        const connection = packet.control_state.flexible_connections.find(value =>
          value.cluster_a_id === primary || value.cluster_b_id === primary);
        if (!connection) throw new Error('Expected actual flexible connection producer output');
        const toAnchor = anchor => {
          const strand = packet.control_state.strands.find(value => value.id === anchor.strand_id);
          return { helix_id: strand.domains[anchor.domain_index].helix_id, bp: anchor.bp_index, direction: anchor.direction };
        };
        const onA = connection.cluster_a_id === primary;
        tether = { moving: toAnchor(onA ? connection.anchor_a : connection.anchor_b),
          fixed: toAnchor(onA ? connection.anchor_b : connection.anchor_a), contour_nm: connection.contour_length_nm };
      } else {
        tether = packet.control_state.placement_constraints.find(value => value.cluster_id === primary)?.tethers[0];
      }
      if (!tether) throw new Error('Expected actual native connection tether producer output');
      const moving = nativeAnchor(tether.moving), fixed = nativeAnchor(tether.fixed);
      const away = moving.clone().sub(fixed);
      if (away.lengthSq() < 1e-12) away.set(1, 0, 0);
      const requestedAnchor = fixed.clone().addScaledVector(away.normalize(), tether.contour_nm + 4);
      delta = requestedAnchor.clone().sub(moving);
      constraintEvidence = { contour_nm: tether.contour_nm, proposed_distance: requestedAnchor.distanceTo(fixed) };
    }
    const requestedTranslation = tc.object.position.clone().add(delta).sub(new THREE.Vector3(...gizmo.getPivot()));
    const requestedRotation = tc.object.quaternion.clone();
    tc.dispatchEvent({ type: 'dragging-changed', value: true });
    tc.object.position.add(delta);
    tc.dispatchEvent({ type: 'change' });
    if (cancel) {
      document.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      await tick();
    } else {
      tc.dispatchEvent({ type: 'dragging-changed', value: false }); await tick();
      if (constraintEvidence) {
        const native = gizmo.getPendingTransform(primary);
        const translationCorrection = new THREE.Vector3(...native.translation).distanceTo(requestedTranslation);
        const rotationCorrection = new THREE.Quaternion(...native.rotation).angleTo(requestedRotation);
        constraintEvidence.correction = translationCorrection + rotationCorrection;
        if (constraintEvidence.correction < 1e-6) throw new Error('Native tether constraint did not alter the deliberately overstretched free proposal');
      }
    }
  }
  if (errors.length) throw new Error(errors.join('\n'));
  if (cancel) {
    if (!cancelled || drafts.length !== initialDrafts) throw new Error('Cancelled native gesture emitted a late draft');
    result = { cancelled: true };
  } else {
    if (drafts.length <= initialDrafts) throw new Error('Native gesture produced no owned draft');
    callbacks.onApply(); await tick();
    if (applied !== 1 || errors.length) throw new Error('Native draft did not reach the owned Apply callback');
    const pending = gizmo.getAllPendingTransforms().map(pose), patch = drafts.at(-1);
    if (rootPivot && (definition(patch).authoring.pivot_id !== `dup:root:${ids.driver}`
      || JSON.stringify(definition(patch).poses.find(row => row.cluster_id === primary)?.pivot) !== JSON.stringify(rootPivot)))
      throw new Error('Duplex draft lost the exact root pivot or its recorded identity');
    for (const value of pending) {
      const emitted = definition(patch).poses.find(row => row.cluster_id === value.cluster_id);
      if (!emitted || ['translation','rotation','pivot'].some(key => JSON.stringify(emitted[key]) !== JSON.stringify(value[key])))
        throw new Error('Emitted complete pose lost the actual native pending transform');
    }
    result = { patch, pending, draft_count: drafts.length, constraint_evidence: constraintEvidence, joint_world_error: jointError };
  }
} finally {
  try { tool?.dispose(); preview.dispose(); }
  finally { for (const channel of channels) channel.close(); dom.window.close(); }
}
if (JSON.stringify(packet) !== original || scene.children.length || camera.layers.mask !== 1 || controls.enabled !== false || released !== 1
  || networkCalls || broadcastCalls)
  throw new Error('Private gesture changed its source or leaked viewport/tool ownership');
process.stdout.write('\n' + JSON.stringify(result));
"""


def gesture_draft(packet, gesture, identities, *, cancel=False, joint_limit=25):
    """Return only the real tool's emitted definition and observed native poses."""
    result = subprocess.run(["node", "--input-type=module", "-e", SCRIPT],
        cwd=Path(__file__).resolve().parents[1],
        input=json.dumps({"packet": packet, "gesture": gesture, "ids": identities, "cancel": cancel,
                         "joint_limit": joint_limit}, allow_nan=False),
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.splitlines()[-1])


@pytest.mark.parametrize("gesture,kind,driver", [
    ("free", "flexible", False), ("flexible", "flexible", False),
    ("joint", "joint", False), ("duplex-link", "duplex", False),
    ("ss-linker", "ss-linker", False), ("ds-linker", "ds-linker", False),
    ("duplex-root", "duplex", True), ("duplex-taut", "duplex", True),
])
def test_native_private_gesture_emits_complete_host_accepted_history(document, gesture, kind, driver):  # noqa: F811
    source, ids = constraint_recipe(kind, driver=driver)
    state.load_design(source)
    before = checkpoint()
    opened = host.prepare(opening(), family="transform")
    observed = gesture_draft(opened, gesture, ids)
    patch = observed["patch"]
    assert observed["pending"] and observed["draft_count"] > 0
    if gesture == "joint":
        assert observed["joint_world_error"] < 1e-8
    if gesture in {"flexible", "ss-linker", "ds-linker", "duplex-taut"}:
        evidence = observed["constraint_evidence"]
        assert evidence["proposed_distance"] > evidence["contour_nm"] + 3
        assert evidence["correction"] > 1e-6  # Constraint was exercised, not a convergence/physical-validity claim.
    if gesture == "duplex-link":
        native = next(pose for pose in observed["pending"] if pose["cluster_id"] == ids["auxiliary"])
        original = next(pose for pose in opened["control_context"]["inputs"]["poses"] if pose["cluster_id"] == ids["auxiliary"])
        assert any(native[field] != original[field] for field in ("translation", "rotation", "pivot"))
    fixed = opened["control_context"]["inputs"]["authoring"]["fixed_cluster_ids"]
    assert patch["authoring"]["fixed_cluster_ids"] == fixed
    assert not set(fixed) & {pose["cluster_id"] for pose in patch["poses"]}
    evaluated = host.evaluate(update(opened, params=patch), family="transform")
    assert evaluated["evaluated_command_kind"] == "placement-poses"
    unchanged(before)
    receipt = host.apply(update(opened, sequence=2, params=patch), family="transform")
    candidate = state.get_or_404()
    assert receipt["status"] == "applied" and receipt["revision"] == before["revision"] + 1
    assert state.undo_depth() == len(before["history"]) + 1
    entry = next(row for row in candidate.feature_log if row.id == FEATURE)
    assert entry.params["poses"] == patch["poses"]
    assert candidate.feature_log[-1].id == source.feature_log[-1].id
    for identity in fixed:
        assert next(owner for owner in candidate.cluster_transforms if owner.id == identity) == next(
            owner for owner in source.cluster_transforms if owner.id == identity)
    loaded = m.Design.from_json(candidate.to_json())
    assert loaded.model_dump(mode="json") == candidate.model_dump(mode="json")
    verified(loaded)
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]


def test_cancel_drops_queued_real_native_gesture_and_preserves_backend_source(document):  # noqa: F811
    source, ids = constraint_recipe("flexible")
    state.load_design(source)
    before = checkpoint()
    opened = host.prepare(opening(), family="transform")
    assert gesture_draft(opened, "flexible", ids, cancel=True) == {"cancelled": True}
    assert host.cancel(cancellation(opened), family="transform")["status"] == "cancelled"
    unchanged(before)
