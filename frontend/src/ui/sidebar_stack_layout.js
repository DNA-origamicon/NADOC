export const MIN_SIDEBAR_WIDTH = 200
export const DEFAULT_SIDEBAR_WIDTH = 280
export const MAX_SIDEBAR_WIDTH = 600
export const MIN_WORKSPACE_WIDTH = 320

export function sidebarBudget(mainWidth, rightWidth, stripsWidth) {
  return Math.max(0, mainWidth - rightWidth - stripsWidth - MIN_WORKSPACE_WIDTH)
}
export function fitSidebarWidths(widths, budget) {
  const fitted = widths.map(width => Math.max(MIN_SIDEBAR_WIDTH, Math.min(MAX_SIDEBAR_WIDTH, Number(width) || DEFAULT_SIDEBAR_WIDTH)))
  while (fitted.length && fitted.length * MIN_SIDEBAR_WIDTH > budget) fitted.pop()
  let excess = Math.max(0, fitted.reduce((a, b) => a + b, 0) - budget)
  for (let i = fitted.length - 1; i >= 0 && excess > 0; i--) {
    const reduction = Math.min(excess, fitted[i] - MIN_SIDEBAR_WIDTH)
    fitted[i] -= reduction
    excess -= reduction
  }
  return fitted
}
