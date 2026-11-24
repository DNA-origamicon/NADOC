// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { readCornerStream } from './corner.js'

function response(parts) {
  const encoder = new TextEncoder()
  return new Response(new ReadableStream({ start(controller) {
    for (const part of parts) controller.enqueue(encoder.encode(part))
    controller.close()
  } }), { status: 200 })
}
it('reads split NDJSON records in order and accepts a final record without newline', async () => {
  const events = []
  await readCornerStream(response(['{"type":"gu', 'ide","guide":{}}\n{"type":"progress","percent":50}\n',
    '{"type":"ready","candidate":{}}']), event => events.push(event))
  expect(events.map(event => event.type)).toEqual(['guide', 'progress', 'ready'])
})
it('does not mistake an interrupted stream or a server rejection for a ready preview', async () => {
  await expect(readCornerStream(response(['{"type":"progress","percent":50}\n']), vi.fn())).rejects.toThrow('before the Full geometry')
  await expect(readCornerStream(response(['{"type":"error","message":"No duplex at plane"}\n']), vi.fn())).rejects.toThrow('No duplex at plane')
  await expect(readCornerStream(new Response('{"detail":"Source changed"}', { status: 409 }), vi.fn())).rejects.toThrow('Source changed')
})
