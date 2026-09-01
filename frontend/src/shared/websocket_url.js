/** Build a same-origin WebSocket URL without creating HTTPS mixed content. */
export function webSocketUrl(path, locationLike = globalThis.location) {
  const protocol = locationLike?.protocol === 'https:' ? 'wss:' : 'ws:'
  const normalizedPath = String(path || '').startsWith('/') ? path : `/${path}`
  return `${protocol}//${locationLike?.host || ''}${normalizedPath}`
}
