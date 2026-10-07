/** Colors for authoritative captured strand animation. No geometry generator. */
/** Role → default hex color. A renderer may override via createStrandRenderer opts. */
export const ROLE_COLOR = {
  A: 0x58a6ff,           // unzip strand A (pull up)   — blue
  B: 0xff7c7c,           // unzip strand B (pull down)  — red
  substrate: 0x8b949e,   // displacement spine          — gray
  invader: 0x3fb950,     // displacement invader        — green
  incumbent: 0xf85149,   // displacement incumbent      — red
}
