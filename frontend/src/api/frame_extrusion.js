/** Commit responses use the same geometry/store synchronization as desktop edits. */
export function createFrameExtrusionAPI({ request, sync }) {
  return {
    refreshNativeVRScene: async body => {
      let pinned = { ...body }
      for (let attempt = 0; attempt < 3; attempt++) {
        const result = await request('POST', '/vr/scene-refresh', pinned)
        if (result?.published) return result
        const current = await request('GET', '/design')
        if (current?.design?.id !== body.expected_design_id ||
            !Number.isSafeInteger(current.revision) || current.revision <= pinned.expected_revision) return null
        // Only refresh a newer canonical revision; never replay the mutation.
        pinned = { ...body, expected_revision: current.revision }
      }
      return null
    },
    validateFrameExtrusion: body => request('POST', '/design/frame-extrusion/validate', body),
    addFrameExtrusion: async body => {
      const response = await request('POST', '/design/frame-extrusion', body)
      return response ? sync(response) : null
    },
  }
}
