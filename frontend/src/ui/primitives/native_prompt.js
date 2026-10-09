// Optional adapter installed by the native VR session. Desktop callers retain
// their normal modal unless they explicitly opt in to an approved VR workflow.
let handler = null
export function setNativePromptHandler(next) { handler = next }
export function nativePrompt(opts) { return handler?.(opts) ?? null }
