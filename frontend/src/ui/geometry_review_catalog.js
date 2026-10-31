// Prepared evidence only. Loading a review never runs a candidate fitting policy.
const attachmentURL = new URL('./geometry_review_data/platform-attachment.json.gz', import.meta.url).href
const directURL = new URL('./geometry_review_data/direct-linker.json.gz', import.meta.url).href
const nativeDirectURL = new URL('./geometry_review_data/direct-native.json.gz', import.meta.url).href

async function loadEvidence(url, { signal }) {
  const response = await fetch(url, { signal })
  if (!response.ok) throw new Error(`Could not load geometry evidence (HTTP ${response.status}).`)
  // Vite serves .json.gz with Content-Encoding:gzip, which fetch decompresses.
  // Other static servers serve the gzip file as-is. Inspect the received bytes
  // so both development and built apps load the same evidence exactly once.
  const bytes = new Uint8Array(await response.arrayBuffer())
  const body = bytes[0] === 0x1f && bytes[1] === 0x8b
    ? new Response(bytes).body.pipeThrough(new DecompressionStream('gzip'))
    : bytes
  return new Response(body).json()
}
const loadAttachment = options => loadEvidence(attachmentURL, options)
const loadDirect = options => loadEvidence(directURL, options)
const loadNativeDirect = options => loadEvidence(nativeDirectURL, options)
const loadDirectRenderer = () => import('./direct_linker_review.js')

// Add future prepared issues here, using their own loader and content renderer.
// Entries sharing a loader share one in-memory bundle until the workspace closes.
export const geometryReviewCases = [
  { id: 'platform', title: 'Platform attachment — rejected draft / candidate', load: loadAttachment },
  { id: 'clear', title: '2HB — unchanged clean control', load: loadAttachment, control: 'clear' },
  { id: 'pierced', title: '2HB — unchanged pierced control', load: loadAttachment, control: 'pierced' },
  { id: 'direct', title: 'Direct root linker — isolated diagnostic', load: loadDirect, loadRenderer: loadDirectRenderer },
  { id: 'direct-native', title: 'Direct — native Extrude, unreachable layout', load: loadDirect, loadRenderer: loadDirectRenderer, control: 'native' },
  { id: 'direct-contact', title: 'Direct — phase control with atom contact', load: loadDirect, loadRenderer: loadDirectRenderer, control: 'contact' },
  { id: 'direct-reachable', title: 'Direct — same-cluster strain exemption', load: loadNativeDirect, loadRenderer: loadDirectRenderer },
]
