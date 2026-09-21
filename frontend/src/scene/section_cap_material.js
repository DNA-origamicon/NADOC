/** Trusted section-cap shader shared by the editor and prepared viewer. */
export function sectionCapShader(shader) {
  shader.fragmentShader = shader.fragmentShader.replace('#include <color_fragment>', `#include <color_fragment>
    float stripe = mod(gl_FragCoord.x + gl_FragCoord.y, 12.0);
    float ink = 1.0 - smoothstep(0.7, 1.8, min(stripe, 12.0 - stripe));
    diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.18, 0.27, 0.32), ink * 0.8);`)
}
