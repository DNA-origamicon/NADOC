// Prepared evidence only. Loading a review never runs a candidate fitting policy.
const attachmentURL = new URL('./geometry_review_data/platform-attachment.json.gz', import.meta.url).href

async function loadAttachment({ signal }) {
  const response = await fetch(attachmentURL, { signal })
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

// Add future prepared issues here, using their own loader and content renderer.
// Entries sharing a loader share one in-memory bundle until the workspace closes.
export const geometryReviewCases = [
  { id: 'platform', title: 'Platform attachment — rejected draft / candidate', load: loadAttachment },
  { id: 'clear', title: '2HB — unchanged clean control', load: loadAttachment, control: 'clear' },
  { id: 'pierced', title: '2HB — unchanged pierced control', load: loadAttachment, control: 'pierced' },
]
