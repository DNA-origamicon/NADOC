R"GLSL(
float annotationSegment(vec2 p, vec2 a, vec2 b) {
    vec2 ab=b-a;return length(p-a-ab*clamp(dot(p-a,ab)/dot(ab,ab),0.0,1.0));
}
vec4 annotationGlyph(vec2 p,float kind,vec3 tint) {
    float d=kind<3.5 ? abs(length(p)-0.28)-0.045 :
        min(annotationSegment(p,vec2(-0.22),vec2(0.22)),
            annotationSegment(p,vec2(-0.22,0.22),vec2(0.22,-0.22)))-0.038;
    float aa=max(fwidth(d),0.001);
    float core=1.0-smoothstep(-aa,aa,d);
    float outline=1.0-smoothstep(0.018-aa,0.018+aa,d);
    float glow=0.60*exp(-pow(max(d,0.0)/0.065,2.0));
    // Small dark separation rim keeps the hot core readable against both DNA
    // and its own halo; the ring's centre stays open.
    vec3 color=mix(tint,vec3(0.025),outline*(1.0-core));
    color=mix(color,mix(tint,vec3(1.0),0.58),core);
    return vec4(color,max(core,max(outline*0.85,glow)));
}
)GLSL"
