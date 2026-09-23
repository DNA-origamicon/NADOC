import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { writeFileSync } from 'node:fs'

// Forward-project saved geometry against the actual noisy capture pose. Missing
// presentation telemetry fails; never substitute the requested pose as evidence.
export function verifyVRPlacementMapping(info, stage, design) {
  try {
    const report = execFileSync('uv',['run','python','-m','tools.vr_workflows.placement_oracle',
      info.outputPath(stage,'freeform-capture.json')],{
      cwd:path.resolve(process.cwd(),'..'),input:JSON.stringify(design),encoding:'utf8',timeout:10000,
    })
    writeFileSync(info.outputPath(stage,'placement-mapping.json'),report)
    return JSON.parse(report)
  } catch (error) {
    writeFileSync(info.outputPath(stage,'placement-mapping-failure.txt'),
      `${error.stdout || ''}\n${error.stderr || ''}\n${error.message}`)
    throw error
  }
}
