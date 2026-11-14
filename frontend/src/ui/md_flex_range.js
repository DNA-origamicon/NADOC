/** Frame numbers in this UI are one-based, with an inclusive end. */
export function defaultFlexRange(total) {
  return { start: Math.max(1, total - 199), end: total, interval: 1 }
}

export function validateFlexRange(values, total) {
  const range = Object.fromEntries(['start', 'end', 'interval'].map(key => [key, Number(values[key])]))
  if (!Object.values(range).every(Number.isSafeInteger) || range.interval < 1 || range.start < 1 ||
      range.end < range.start || range.end > total) {
    throw new Error(`Choose whole frame numbers: 1 ≤ Start ≤ End ≤ ${total}, and Interval ≥ 1.`)
  }
  return range
}

export function flexRangeQuery(range) {
  if (!range) return ''
  return `?${new URLSearchParams(Object.entries(range).filter(([, value]) => value != null))}`
}

export function flexRangeKey(range) {
  return JSON.stringify({ start: range?.start ?? null, end: range?.end ?? null, interval: range?.interval ?? 1 })
}
