// The native tablet uses a 768px panel. Reserve its lower-right area for status
// without allowing an export error or an unbroken identifier to cross the frame.
export const VIEW_TOOL_MESSAGE = Object.freeze({ x: 410, y: 644, width: 326, lineHeight: 23, lines: 4 })

export function viewToolMessageLines(context, message) {
  const box = VIEW_TOOL_MESSAGE
  let remaining = Array.from(String(message).trim().replace(/\s+/gu, ' '))
  const lines = []
  while (remaining.length && lines.length < box.lines) {
    const last = lines.length === box.lines - 1
    const complete = remaining.join('')
    if (context.measureText(complete).width <= box.width) {
      lines.push(complete)
      break
    }
    const suffix = last ? '...' : ''
    let low = 0, high = remaining.length
    while (low < high) {
      const middle = Math.ceil((low + high) / 2)
      if (context.measureText(remaining.slice(0, middle).join('') + suffix).width <= box.width) low = middle
      else high = middle - 1
    }
    const space = remaining.slice(0, low + 1).lastIndexOf(' ')
    const count = space > 0 ? space : low
    lines.push(remaining.slice(0, count).join('').trimEnd() + suffix)
    if (last || count === 0) break
    remaining = remaining.slice(count)
    while (remaining[0] === ' ') remaining.shift()
  }
  return lines
}

export function drawViewToolMessage(context, message) {
  const box = VIEW_TOOL_MESSAGE
  for (const [index, line] of viewToolMessageLines(context, message).entries()) {
    context.fillText(line, box.x, box.y + index * box.lineHeight)
  }
}
