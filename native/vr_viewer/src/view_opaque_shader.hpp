#pragma once
#include <cmath>
#include <cstdlib>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>

namespace nadoc_vr::view_opaque {
inline bool requested(std::string_view value) {
    if(value=="0")return false;
    if(value.empty() || value=="1")return true;
    throw std::runtime_error("NADOC_VR_OPAQUE_VIEW_SHADER requires 0 or 1");
}
inline bool requestedFromEnvironment() {
    const auto* value=std::getenv("NADOC_VR_OPAQUE_VIEW_SHADER");return requested(value?value:"");
}
struct Eligibility {
    bool eligible=false;
    const char* reason="not_checked";
};
template<class Vertex> Eligibility vertex(const Vertex& v) {
    for(unsigned i=0;i<3;++i)if(!std::isfinite(v.p[i]) || !std::isfinite(v.normal[i]))return {false,"nonfinite_vertex"};
    for(unsigned i=0;i<4;++i)if(!std::isfinite(v.color[i]))return {false,"nonfinite_vertex"};
    for(unsigned i=0;i<2;++i)if(!std::isfinite(v.uv[i]))return {false,"nonfinite_vertex"};
    if(v.color.a!=1)return {false,"vertex_alpha_not_one"};
    if(!(v.uv.x<0))return {false,"textured_vertex"};
    if(v.uv.x>-std::numeric_limits<float>::min())return {false,"subnormal_negative_uv"};
    return {true,"eligible"};
}
template<class Instance> Eligibility instance(const Instance& value) {
    for(unsigned c=0;c<4;++c)for(unsigned r=0;r<4;++r)if(!std::isfinite(value.matrix[c][r]))return {false,"nonfinite_instance"};
    for(unsigned i=0;i<4;++i)if(!std::isfinite(value.color[i]))return {false,"nonfinite_instance"};
    if(value.color.a!=1)return {false,"instance_alpha_not_one"};
    return {true,"eligible"};
}
// Evaluated on the file-reading worker after normalization. Lines, sprites and
// panels are deliberately excluded because their draws always use legacy.
template<class Vertices,class Batches> Eligibility classify(const Vertices& triangles,const Batches& batches) {
    bool any=!triangles.empty();
    for(const auto& v:triangles){auto e=vertex(v);if(!e.eligible)return e;}
    for(const auto& batch:batches) {
        if(batch.vertices.empty() || batch.instances.empty())continue;
        any=true;
        for(const auto& v:batch.vertices){auto e=vertex(v);if(!e.eligible)return e;}
        for(const auto& value:batch.instances){auto e=instance(value);if(!e.eligible)return e;}
    }
    return any?Eligibility{true,"eligible"}:Eligibility{false,"no_surface_geometry"};
}
inline bool active(bool enabled,const Eligibility& eligibility,bool shadow) {
    return enabled && eligibility.eligible && !shadow;
}
// Byte-identical legacy vertex shader. No source geometry/normal arithmetic or
// primitive order changes accompany the opaque fragment specialization.
inline constexpr const char* vertexSource=R"(#version 330 core
layout(location=0) in vec3 p;layout(location=1) in vec4 color;layout(location=2) in vec2 uv;
layout(location=3) in mat4 instanceMatrix;layout(location=7) in vec4 instanceColor;
layout(location=8) in vec3 normal;
uniform mat4 vp,worldModel;uniform bool instanced;
out vec4 c;out vec2 t;out vec3 vNormal;out vec3 vWorldPosition;
out vec3 vColor;flat out int vTwoSided;flat out uint vSelection;flat out uint vObjectId;
void main(){mat4 m=instanced?instanceMatrix:mat4(1);vec4 point=m*vec4(p,1);
gl_Position=vp*point;c=color*(instanced?instanceColor:vec4(1));t=uv;
vWorldPosition=(worldModel*point).xyz;vNormal=transpose(inverse(mat3(worldModel*m)))*normal;
vColor=c.rgb;vTwoSided=1;vSelection=0u;vObjectId=0u;})";
inline std::string fragment(std::string_view canonicalLit,std::string_view glass,bool opaque) {
    const auto main=canonicalLit.find("    void main() {");
    if(main==std::string_view::npos)throw std::runtime_error("Canonical lighting fragment main not found");
    std::string result(canonicalLit.substr(0,main));
    if(opaque) {
        result+=R"(in vec4 c;
void main(){
    vec3 color=pow(max(c.rgb,vec3(0)),vec3(1.0/2.2));
    if(dot(vNormal,vNormal)>1e-12){vec3 n=normalize(vNormal)*(gl_FrontFacing?1.0:-1.0);
        color*=sceneLighting(n);}
    outColor=vec4(color,1.0);outObjectId=0u;
})";
    } else {
        result+="in vec4 c;in vec2 t;uniform sampler2D atlas;uniform bool shadowPass;\n";
        result+=glass;
        result+=R"(
void main(){
    vec4 tex=t.x<0?vec4(1):texture(atlas,t);
    float alpha=c.a*tex.a;if(alpha<.02)discard;
    if(shadowPass){if(dot(vNormal,vNormal)<1e-12)discard;outColor=vec4(1);outObjectId=0u;return;}
    vec3 color=pow(max(c.rgb,vec3(0)),vec3(1.0/2.2))*tex.rgb;
    if(dot(vNormal,vNormal)>1e-12){vec3 n=normalize(vNormal)*(gl_FrontFacing?1.0:-1.0);
        color*=sceneLighting(n);}
    outColor=frostedMenu(vec4(color,alpha));outObjectId=0u;
})";
    }
    return result;
}
} // namespace nadoc_vr::view_opaque
