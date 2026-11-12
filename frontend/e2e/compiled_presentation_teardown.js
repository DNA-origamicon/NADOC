import cleanup from './global-teardown.js'
import { rm } from 'node:fs/promises'
export default async function teardown() {
  try { await cleanup() }
  finally { await rm(process.env.NADOC_COMPILE_E2E_ROOT, { recursive: true, force: true }) }
}
