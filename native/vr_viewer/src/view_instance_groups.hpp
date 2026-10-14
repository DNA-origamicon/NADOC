#pragma once
#include <array>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace nadoc_vr::view_groups {
inline constexpr size_t groupSize=8,maxBaseVertices=72,maxExpandedBytes=32*1024*1024;
inline constexpr unsigned textureUnit=9;
struct Limits {uint64_t textureTexels=0;bool vertexSampler=false,textureUnitAvailable=false;};
struct Plan {bool eligible=false;const char* reason="not_checked";size_t expandedVertices=0,expandedBytes=0;};
inline bool requested(std::string_view value) {
    if(value=="0")return false;
    if(value.empty() || value=="1")return true;
    throw std::runtime_error("NADOC_VR_GROUPED_VIEW_INSTANCES requires 0 or 1");
}
inline bool requestedFromEnvironment(){const auto* value=std::getenv("NADOC_VR_GROUPED_VIEW_INSTANCES");return requested(value?value:"");}
inline Plan plan(size_t vertices,size_t instances,size_t stride,const Limits& limits,size_t remaining=maxExpandedBytes) {
    if(!limits.vertexSampler || !limits.textureUnitAvailable)return {false,"texture_sampler_unavailable"};
    if(!vertices || vertices%3 || vertices>maxBaseVertices)return {false,"base_mesh_outside_small_triangle_limit"};
    if(instances<groupSize)return {false,"too_few_instances"};
    if(instances>size_t(std::numeric_limits<int32_t>::max())/5 || uint64_t(instances)*5>limits.textureTexels)return {false,"instance_texel_limit"};
    if(!stride || stride>std::numeric_limits<size_t>::max()/(vertices*groupSize))return {false,"expanded_byte_overflow"};
    const auto bytes=vertices*groupSize*stride;
    if(bytes>remaining)return {false,"expanded_vertex_budget"};
    return {true,"eligible",vertices*groupSize,bytes};
}
template<class Vertex> std::vector<Vertex> expand(const std::vector<Vertex>& vertices) {
    if(vertices.empty() || vertices.size()>maxBaseVertices || vertices.size()%3)throw std::runtime_error("Invalid grouped base mesh");
    std::vector<Vertex> result;result.reserve(vertices.size()*groupSize);
    for(size_t i=0;i<groupSize;++i)result.insert(result.end(),vertices.begin(),vertices.end());
    return result;
}
struct Draw {int vertices=0,instances=0,firstInstance=0;};
inline std::array<Draw,2> draws(size_t vertices,size_t instances) {
    if(!vertices || vertices>maxBaseVertices || vertices%3 || instances>size_t(std::numeric_limits<int32_t>::max())/5)throw std::runtime_error("Invalid grouped draw size");
    const size_t full=instances/groupSize,remainder=instances%groupSize;
    return {{{int(vertices*groupSize),int(full),0},{int(vertices*remainder),remainder?1:0,int(full*groupSize)}}};
}
inline std::string vertexShader(std::string_view legacy) {
    std::string result(legacy);
    auto replace=[&](std::string_view before,std::string_view after){const auto at=result.find(before);if(at==std::string::npos || result.find(before,at+before.size())!=std::string::npos)throw std::runtime_error("Legacy grouped shader anchor changed");result.replace(at,before.size(),after);};
    replace("void main(){",R"(uniform samplerBuffer uGroupedInstances;
uniform int uGroupBaseVertices,uGroupFirstInstance;
void main(){)" );
    replace("mat4 m=instanced?instanceMatrix:mat4(1);",R"(int logicalInstance=gl_InstanceID*8+gl_VertexID/uGroupBaseVertices+uGroupFirstInstance;
int texel=logicalInstance*5;
mat4 m=mat4(texelFetch(uGroupedInstances,texel),texelFetch(uGroupedInstances,texel+1),texelFetch(uGroupedInstances,texel+2),texelFetch(uGroupedInstances,texel+3));)" );
    replace("c=color*(instanced?instanceColor:vec4(1));","c=color*texelFetch(uGroupedInstances,texel+4);");
    return result;
}
} // namespace nadoc_vr::view_groups
