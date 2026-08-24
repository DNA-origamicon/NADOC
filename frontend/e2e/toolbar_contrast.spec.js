import { test, expect } from '@playwright/test'

function luminance(hex) {
  const channels = hex.match(/[\da-f]{2}/gi).map(value => parseInt(value, 16) / 255)
    .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
}

function contrast(first, second) {
  const a = luminance(first)
  const b = luminance(second)
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

for (const [name, url] of [['3D workspace', '/'], ['caDNAno path view', '/cadnano-editor.html']]) {
  test(`${name} toolbar uses readable raised-neutral controls`, async ({ page }) => {
    await page.goto(url)
    const appearance = await page.locator('#view-tools .sf-btn:not(.active)').first().evaluate(button => {
      const style = getComputedStyle(button)
      const label = getComputedStyle(button.querySelector('.sf-label-text'))
      const rgbToHex = value => `#${value.match(/\d+/g).slice(0, 3)
        .map(channel => Number(channel).toString(16).padStart(2, '0')).join('')}`
      return {
        background: rgbToHex(style.backgroundColor),
        border: rgbToHex(style.borderTopColor),
        color: rgbToHex(style.color),
        fontSize: parseFloat(label.fontSize),
      }
    })

    expect(appearance.background).toBe('#21262d')
    expect(contrast(appearance.color, appearance.background)).toBeGreaterThanOrEqual(4.5)
    expect(contrast(appearance.border, '#0d1117')).toBeGreaterThanOrEqual(3)
    expect(appearance.fontSize).toBeGreaterThanOrEqual(10)
  })
}
