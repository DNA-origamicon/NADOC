#pragma once
#include <string>
namespace nadoc_vr {
// One fragment predicate shared by meshes, sphere impostors and atomistic bonds.
// Buffer records contain world-to-volume matrices and shape data; no fixed count cap.
inline std::string volumeFragment(std::string source,const std::string& anchor,const std::string& point) {
    const auto version=source.find('\n',source.find("#version"));
    source.insert(version+1,R"GLSL(
        uniform samplerBuffer uVolumes;
        uniform int uVolumeCount;
        uniform int uVolumeLayer;
        uniform float uVolumeOpacity = 1.0;
        bool insideVolume(int i, vec3 world) {
            int b=i*5;
            mat4 transform=mat4(texelFetch(uVolumes,b),texelFetch(uVolumes,b+1),texelFetch(uVolumes,b+2),texelFetch(uVolumes,b+3));
            vec3 p=(transform*vec4(world,1)).xyz;
            vec4 shape=texelFetch(uVolumes,b+4);
            if(abs(p.z)>1) return false;
            if(shape.x==4) return max(abs(p.x),abs(p.y))<=1;
            // Unit circumradius, identical orientation to the persisted hex prism.
            for(int j=0;j<6;++j) {
                float a=(float(j)+0.5)*1.0471975512;
                if(dot(p.xy,vec2(cos(a),sin(a)))>0.8660254038) return false;
            }
            return true;
        }
        bool clippedVolume(vec3 world) {
            if(uVolumeCount==0) return false;
            if(uVolumeLayer>=0) return !insideVolume(uVolumeLayer,world);
            for(int i=0;i<uVolumeCount;++i) if(insideVolume(i,world)) return true;
            return false;
        }
)GLSL");
    auto at=source.find(anchor);
    source.insert(at+anchor.size(),"\nif(clippedVolume("+point+")) discard;\n");
    const auto end=source.rfind('}');
    source.insert(end,"\noutColor.a *= uVolumeOpacity;\n");
    return source;
}
}
