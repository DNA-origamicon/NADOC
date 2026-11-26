/** Limits of the actual backend's data representation, not a scene-size policy.
 * Browser APIs do not report reliable free VRAM. Passing these checks is not an
 * allocation guarantee; allocation/context-loss errors must still be surfaced. */
export function checkTraceGeometry({vertices, triangles}, maxTextureSize = Infinity) {
  if (!Number.isSafeInteger(vertices) || vertices > 0x100000000)
    throw new Error('Path tracing exceeds the renderer’s 32-bit vertex address range.')
  for (const [name, count] of [['vertex attributes', vertices], ['triangle indices', triangles]]) {
    const dimension = Math.ceil(Math.sqrt(count))
    if (dimension > maxTextureSize)
      throw new Error(`WebGL ${name} need a ${dimension}×${dimension} texture; this device reports a ${maxTextureSize}×${maxTextureSize} limit. Try OptiX export.`)
  }
}

export function checkTraceBVH(bvh, maxTextureSize) {
  for (const root of bvh._roots) {
    // Pinned three-mesh-bvh packing: 32-byte nodes, two bounds texels per node.
    const dimension = 2 * Math.ceil(Math.sqrt(root.byteLength / 32 / 2))
    if (dimension > maxTextureSize)
      throw new Error(`WebGL acceleration data need a ${dimension}×${dimension} texture; this device reports a ${maxTextureSize}×${maxTextureSize} limit. Try OptiX export.`)
  }
}

export function checkWebGPUStorage(storage, limits) {
  const maxBytes = Math.min(limits.maxBufferSize, limits.maxStorageBufferBindingSize)
  for (const [name, node] of Object.entries(storage)) {
    const bytes = node?.value?.array?.byteLength ?? 0
    if (bytes > maxBytes)
      throw new Error(`WebGPU ${name} require ${(bytes / 1048576).toFixed(1)} MiB in one buffer; this device reports ${(maxBytes / 1048576).toFixed(1)} MiB. Try OptiX export.`)
  }
}

export function traceDeviceLimits(limits) {
  return Object.fromEntries(['maxBufferSize', 'maxStorageBufferBindingSize', 'maxTextureDimension2D', 'maxTextureArrayLayers']
    .map(name => [name, limits[name]]))
}
