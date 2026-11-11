/** Same joint capture/restore contract for full and single-keyframe previews. */
export function animationPlayOptions(assembly, api) {
  if (!assembly) return {}
  return {
    liveJointValues: Object.fromEntries((assembly.joints ?? []).map(j => [j.id, j.current_value])),
    onJointUpdate: (jointId, value) => api.patchAssemblyJoint(jointId, { current_value: value, _silent: true }),
  }
}
