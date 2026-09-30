/** Generate the same QR cube print kit offered by the Export menu. */
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { qrCubeFiles } from '../src/shared/qr_cube.js'
export { cubeMesh, plateMesh, stl, supportSocket } from '../src/shared/qr_cube.js'

async function main() {
  const output = process.argv[2]
  if (!output) throw Error('Usage: node frontend/scripts/generate-qr-cube.mjs OUTPUT_DIRECTORY')
  await mkdir(output, { recursive: false })
  for (const [name, content] of Object.entries(qrCubeFiles())) {
    await writeFile(resolve(output, name), content)
  }
  console.log(`Wrote six STL files and assembly instructions to ${resolve(output)}`)
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(e => { console.error(e.message); process.exitCode = 1 })
}
