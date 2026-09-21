/** Shared local host discovery. Credentials stay on the hosting PC. */
import { createHash } from 'node:crypto'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
export function shareControlFile(root, port = 5173) {
  return process.env.NADOC_SHARE_CONTROL_FILE ?? join(tmpdir(), `nadoc-share-internet-${createHash('sha256').update(root).digest('hex').slice(0, 12)}-${port}.json`)
}
