import { describe, it, expect } from 'vitest'
import { formatBytes } from './format_bytes.js'

describe('formatBytes', () => {
  it('renders raw bytes with no decimal', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1023)).toBe('1023 B')
  })

  it('scales through KB/MB/GB/TB', () => {
    expect(formatBytes(1024)).toBe('1 KB')
    expect(formatBytes(1536)).toBe('1.5 KB')
    expect(formatBytes(1048576)).toBe('1 MB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5 MB')
    expect(formatBytes(2.5 * 1024 ** 3)).toBe('2.5 GB')
    expect(formatBytes(3 * 1024 ** 4)).toBe('3 TB')
  })

  it('drops a trailing .0', () => {
    expect(formatBytes(2 * 1024 ** 3)).toBe('2 GB')
  })

  it('treats invalid / non-positive input as 0 B', () => {
    expect(formatBytes(-5)).toBe('0 B')
    expect(formatBytes(NaN)).toBe('0 B')
    expect(formatBytes(undefined)).toBe('0 B')
    expect(formatBytes(null)).toBe('0 B')
  })
})
