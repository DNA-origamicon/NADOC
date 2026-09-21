/** Validate the existing provider state without changing unrelated shares. */
export function internetOrigin(status, configuration) {
  if (status.BackendState !== 'Running') throw new Error('The hosting PC must sign in to Tailscale before internet sharing can start. Guests do not need Tailscale.')
  const name = status.Self?.DNSName?.replace(/\.$/, '')
  if (!name || !/^[a-z0-9-]+\.[a-z0-9.-]+\.ts\.net$/i.test(name)) throw new Error('Tailscale HTTPS name is unavailable on this PC')
  const occupied = value => value && typeof value === 'object' && (value.TCP?.['443'] || Object.values(value).some(item => typeof item === 'object' && occupied(item)))
  if (occupied(configuration)) throw new Error('HTTPS port 443 is already used by another Tailscale share. It has been left unchanged.')
  return `https://${name}`
}

export function hasInternetRoute(configuration, origin, target) {
  const host = new URL(origin).hostname + ':443'
  const matches = value => value && typeof value === 'object' && ((value.AllowFunnel?.[host] === true && value.Web?.[host]?.Handlers?.['/']?.Proxy === target) || Object.values(value).some(item => typeof item === 'object' && matches(item)))
  return Boolean(matches(configuration))
}
