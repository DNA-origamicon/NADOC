/** Mirror the native transform display's bounded ordinary-part capacity. */
export const TRANSFORM_DISPLAY_LIMITS = Object.freeze({
  helices: 64, strands: 4096, domains: 8192, records: 65_536, selectors: 8192,
  owners: 32, nativeWork: 131_072, axisPoints: 65_536,
  nodes: 4_000_000, bytes: 128_000_000,
})
