/**
 * Pathview layout constants — world-space pixels.
 *
 * Extracted from `pathview.js` 2026-07-31 (tech-debt TD-03/TD-14). These
 * numbers define the 2D drawing grid and are shared by TWO apps:
 *
 *   - the cadnano editor's `pathview.js` (its only consumer of all of them)
 *   - the 3D app's Domain Designer fork, `frontend/src/ui/overhang_pathview.js`
 *
 * The fork used to import them from `pathview.js` directly, which dragged that
 * 4977-LOC drawing module (and its whole dependency graph) into the main-app
 * bundle for the sake of four numbers. This module has NO imports so either app
 * can pull it in for free.
 *
 * Changing any value here moves geometry in BOTH apps. Pinned by `layout.test.js`.
 */

export const GUTTER    = 40   // left margin before bp 0
export const RULER_H   = 26   // height of the bp ruler strip
export const TOP_PAD   = 18   // gap between ruler and the first helix row
export const BP_W      = 10   // width of one bp cell
export const LABEL_R   = 16   // radius of the gutter helix-label circle

export const CELL_H    = 12   // height of each track cell (strand fills this)
export const PAIR_Y    = CELL_H  // distance between fwdY and revY — adjacent cells
export const ROW_H     = 40   // total row height: 2×CELL_H cells + 16 px inter-helix gap
export const GROUP_GAP = 28   // extra vertical gap between disconnected helix groups

/**
 * Connected-component id for each occupied lattice cell. Cells are connected
 * when their Chebyshev distance is at most one, matching pathview's historical
 * flood fill. A coordinate index limits each BFS step to its nine neighboring
 * cells instead of rescanning every helix.
 *
 * Duplicate coordinates are supported even though valid designs normally have
 * one helix per cell. Component ids follow first-seen input order.
 */
export function connectedCellGroups(cells) {
  const groups = new Int32Array(cells.length)
  groups.fill(-1)
  const byCell = new Map()
  for (let i = 0; i < cells.length; i++) {
    const key = `${cells[i].row}:${cells[i].col}`
    let indices = byCell.get(key)
    if (!indices) byCell.set(key, indices = [])
    indices.push(i)
  }

  let groupId = 0
  for (let seed = 0; seed < cells.length; seed++) {
    if (groups[seed] !== -1) continue
    groups[seed] = groupId
    const queue = [seed]
    let head = 0
    while (head < queue.length) {
      const current = cells[queue[head++]]
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) {
          for (const next of byCell.get(`${current.row + dr}:${current.col + dc}`) ?? []) {
            if (groups[next] !== -1) continue
            groups[next] = groupId
            queue.push(next)
          }
        }
      }
    }
    groupId++
  }
  return groups
}
