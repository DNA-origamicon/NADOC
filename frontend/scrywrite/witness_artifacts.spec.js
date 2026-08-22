import fs from 'node:fs/promises'
import path from 'node:path'
import { test, expect } from '@playwright/test'

const captureDirectory = process.env.SCRYWRITE_WITNESS_CAPTURE_DIR

test('live menu actor-eye snapshots form an inspectable semantic timeline', async ({}, testInfo) => {
  test.skip(!captureDirectory, 'Set SCRYWRITE_WITNESS_CAPTURE_DIR after a live witness capture')

  const entries = await fs.readdir(captureDirectory)
  const metadataNames = entries.filter((name) => name.endsWith('.json')).sort()
  const snapshots = []
  for (const metadataName of metadataNames) {
    const metadataPath = path.join(captureDirectory, metadataName)
    const metadata = JSON.parse(await fs.readFile(metadataPath, 'utf8'))
    const pngPath = path.join(captureDirectory, `${metadata.snapshot}.png`)
    const fingerprintPath = path.join(
      captureDirectory,
      `${metadata.snapshot}.scry-visual`,
    )
    await fs.access(pngPath)
    await fs.access(fingerprintPath)
    snapshots.push(metadata)
    await testInfo.attach(`${String(metadata.frame).padStart(6, '0')}-${metadata.snapshot}`, {
      path: pngPath,
      contentType: 'image/png',
    })
    await testInfo.attach(`${metadata.snapshot}-state.json`, {
      body: Buffer.from(`${JSON.stringify(metadata, null, 2)}\n`),
      contentType: 'application/json',
    })
  }
  snapshots.sort((first, second) => first.frame - second.frame)

  expect(snapshots.map((snapshot) => snapshot.snapshot)).toEqual([
    'options_open',
    'options_tools_hover',
    'tools_open',
    'tools_move_rotate_hover',
    'move_rotate_active',
  ])
  expect(snapshots.every((snapshot) => snapshot.layout === 'valid')).toBe(true)
  expect(snapshots.map((snapshot) => snapshot.menu)).toEqual([
    'options',
    'options',
    'tools',
    'tools',
    'tools',
  ])
  expect(snapshots[1].hover).toBe('tools')
  expect(snapshots[3].hover).toBe('move_rotate')
  expect(snapshots.at(-1)).toMatchObject({
    tool: 'move_rotate',
    status: 'SELECT TARGET',
  })
})
