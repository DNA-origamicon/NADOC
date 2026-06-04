/**
 * Pure screen→NDC conversion extracted from main.js. Unit-tested in ndc.test.js.
 */

/**
 * Client (viewport) coords → normalized device coords (−1..1, y up) given the
 * canvas's bounding rect ({left, top, width, height}). (Was `_canvasNdc`.)
 */
export function clientToNdc(clientX, clientY, rect) {
  return {
    x:  ((clientX - rect.left) / rect.width)  * 2 - 1,
    y: -((clientY - rect.top)  / rect.height) * 2 + 1,
  }
}
