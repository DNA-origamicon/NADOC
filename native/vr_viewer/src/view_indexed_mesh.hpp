#pragma once
#include <array>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <map>
#include <new>
#include <stdexcept>
#include <string_view>
#include <type_traits>
#include <vector>
#include "view_instance_groups.hpp"

namespace nadoc_vr::view_indexed {
// Keep the small-mesh grouping path untouched. Preparation is bounded per mesh
// and per published view; this is exact attribute indexing, never a position weld.
inline constexpr size_t minBaseVertices=73,maxBaseVertices=4096,maxDerivedBytes=8*1024*1024;
struct Plan {
    bool eligible=false;
    const char* reason="not_checked";
    size_t originalVertices=0,uniqueVertices=0,indexCount=0,derivedBytes=0;
};
inline bool requested(std::string_view value) {
    if(value=="0")return false;
    if(value.empty() || value=="1")return true;
    throw std::runtime_error("NADOC_VR_INDEXED_VIEW_MESHES requires 0 or 1");
}
inline bool requestedFromEnvironment(){const auto* value=std::getenv("NADOC_VR_INDEXED_VIEW_MESHES");return requested(value?value:"");}
template<class Vertex> struct Mesh {Plan plan;std::vector<Vertex> vertices;std::vector<uint32_t> indices;};
template<class Vertex> Mesh<Vertex> build(const std::vector<Vertex>& original,size_t remaining=maxDerivedBytes) {
    static_assert(std::is_trivially_copyable_v<Vertex>);
    // The actual wire record is 48 bytes, without padding; bound generic callers
    // too so neither map keys nor retained buffers can escape the worker budget.
    static_assert(sizeof(Vertex)<=256);
    Mesh<Vertex> out;out.plan.originalVertices=original.size();
    if(original.size()<minBaseVertices || original.size()>maxBaseVertices || original.size()%3){out.plan.reason="base_mesh_outside_indexed_limit";return out;}
    const auto worstBytes=original.size()*(sizeof(Vertex)+sizeof(uint32_t));
    if(worstBytes>remaining){out.plan.reason="derived_vertex_budget";return out;}
    try {
        using Bytes=std::array<unsigned char,sizeof(Vertex)>;
        std::map<Bytes,uint32_t> lookup;
        out.vertices.reserve(original.size());out.indices.reserve(original.size());
        for(const auto& vertex:original){
            Bytes bytes;std::memcpy(bytes.data(),&vertex,sizeof(Vertex));
            const auto [it,inserted]=lookup.emplace(bytes,uint32_t(out.vertices.size()));
            if(inserted){out.vertices.emplace_back();std::memcpy(&out.vertices.back(),&vertex,sizeof(Vertex));}
            out.indices.push_back(it->second);
        }
        out.plan.uniqueVertices=out.vertices.size();out.plan.indexCount=out.indices.size();
        // Capacity, rather than just useful bytes, is charged to the CPU budget.
        out.plan.derivedBytes=out.vertices.capacity()*sizeof(Vertex)+out.indices.capacity()*sizeof(uint32_t);
        if(out.plan.derivedBytes>remaining){
            out.plan.reason="derived_capacity_budget";
            std::vector<Vertex>().swap(out.vertices);std::vector<uint32_t>().swap(out.indices);out.plan.derivedBytes=0;return out;
        }
        if(out.vertices.size()*sizeof(Vertex)+out.indices.size()*sizeof(uint32_t)>=original.size()*sizeof(Vertex)){
            out.plan.reason="no_storage_or_vertex_reuse_benefit";
            std::vector<Vertex>().swap(out.vertices);std::vector<uint32_t>().swap(out.indices);out.plan.derivedBytes=0;return out;
        }
        out.plan.eligible=true;out.plan.reason="eligible";
    } catch(const std::bad_alloc&) {
        std::vector<Vertex>().swap(out.vertices);std::vector<uint32_t>().swap(out.indices);
        out.plan.eligible=false;out.plan.reason="optional_cpu_allocation_failed";out.plan.derivedBytes=0;
    }
    return out;
}
inline bool resourcesComplete(const Plan& plan,size_t vertexStride,int64_t vertexBytes,int64_t indexBytes){
    return plan.eligible && vertexBytes>=0 && indexBytes>=0 &&
        uint64_t(vertexBytes)==plan.uniqueVertices*vertexStride && uint64_t(indexBytes)==plan.indexCount*sizeof(uint32_t);
}
inline bool groupsRequested(std::string_view value) {
    if(value=="0")return false;
    if(value.empty() || value=="1")return true;
    throw std::runtime_error("NADOC_VR_GROUPED_INDEXED_MESHES requires 0 or 1");
}
inline bool groupsRequestedFromEnvironment(){const auto* value=std::getenv("NADOC_VR_GROUPED_INDEXED_MESHES");return groupsRequested(value?value:"");}
struct GroupPlan {
    bool eligible=false;
    const char* reason="not_checked";
    size_t uniqueVertices=0,indexCount=0,expandedVertices=0,expandedIndexCount=0,derivedBytes=0;
};
inline GroupPlan planGroups(const Plan& indexed,size_t instances,size_t stride,
                            const nadoc_vr::view_groups::Limits& limits,size_t remaining=maxDerivedBytes) {
    GroupPlan out;out.uniqueVertices=indexed.uniqueVertices;out.indexCount=indexed.indexCount;
    if(!indexed.eligible || !indexed.uniqueVertices || indexed.uniqueVertices>indexed.originalVertices ||
       indexed.originalVertices<minBaseVertices || indexed.originalVertices>maxBaseVertices ||
       indexed.indexCount!=indexed.originalVertices || indexed.indexCount%3){out.reason="indexed_mesh_unavailable";return out;}
    if(!limits.vertexSampler || !limits.textureUnitAvailable){out.reason="texture_sampler_unavailable";return out;}
    if(instances<nadoc_vr::view_groups::groupSize){out.reason="too_few_instances";return out;}
    if(instances>size_t(std::numeric_limits<int32_t>::max())/5 || uint64_t(instances)*5>limits.textureTexels){out.reason="instance_texel_limit";return out;}
    if(!stride || stride>256){out.reason="invalid_vertex_stride";return out;}
    out.expandedVertices=indexed.uniqueVertices*nadoc_vr::view_groups::groupSize;
    out.expandedIndexCount=indexed.indexCount*nadoc_vr::view_groups::groupSize;
    out.derivedBytes=out.expandedVertices*stride+out.expandedIndexCount*sizeof(uint32_t);
    if(out.derivedBytes>remaining){out.reason="derived_vertex_budget";return out;}
    out.eligible=true;out.reason="eligible";return out;
}
template<class Vertex> struct GroupMesh {GroupPlan plan;std::vector<Vertex> vertices;std::vector<uint32_t> indices;};
template<class Vertex> GroupMesh<Vertex> expandGroups(const std::vector<Vertex>& vertices,
    const std::vector<uint32_t>& indices,const GroupPlan& plan,size_t remaining=maxDerivedBytes) {
    static_assert(std::is_trivially_copyable_v<Vertex> && sizeof(Vertex)<=256);
    GroupMesh<Vertex> out;out.plan=plan;
    if(!plan.eligible){out.plan.derivedBytes=0;return out;}
    if(vertices.size()!=plan.uniqueVertices || indices.size()!=plan.indexCount ||
       !vertices.size() || vertices.size()>maxBaseVertices || indices.size()>maxBaseVertices || indices.size()%3 ||
       plan.expandedVertices!=vertices.size()*nadoc_vr::view_groups::groupSize ||
       plan.expandedIndexCount!=indices.size()*nadoc_vr::view_groups::groupSize ||
       plan.derivedBytes!=plan.expandedVertices*sizeof(Vertex)+plan.expandedIndexCount*sizeof(uint32_t)){
        out.plan.eligible=false;out.plan.reason="invalid_group_plan";out.plan.derivedBytes=0;return out;
    }
    if(plan.derivedBytes>remaining){out.plan.eligible=false;out.plan.reason="derived_vertex_budget";out.plan.derivedBytes=0;return out;}
    for(const auto index:indices)if(index>=vertices.size()){out.plan.eligible=false;out.plan.reason="invalid_index";out.plan.derivedBytes=0;return out;}
    try {
        out.vertices.resize(plan.expandedVertices);out.indices.reserve(plan.expandedIndexCount);
        for(size_t group=0;group<nadoc_vr::view_groups::groupSize;++group){
            std::memcpy(out.vertices.data()+group*vertices.size(),vertices.data(),vertices.size()*sizeof(Vertex));
            for(const auto index:indices)out.indices.push_back(uint32_t(index+group*vertices.size()));
        }
        out.plan.derivedBytes=out.vertices.capacity()*sizeof(Vertex)+out.indices.capacity()*sizeof(uint32_t);
        if(out.plan.derivedBytes>remaining){out.plan.eligible=false;out.plan.reason="derived_capacity_budget";}
    } catch(const std::bad_alloc&) {out.plan.eligible=false;out.plan.reason="optional_cpu_allocation_failed";}
    if(!out.plan.eligible){std::vector<Vertex>().swap(out.vertices);std::vector<uint32_t>().swap(out.indices);out.plan.derivedBytes=0;}
    return out;
}
struct GroupDraw {int indexCount=0,instances=0,firstInstance=0;};
inline std::array<GroupDraw,2> groupDraws(size_t indexCount,size_t instances) {
    if(!indexCount || indexCount>maxBaseVertices || indexCount%3 || instances>size_t(std::numeric_limits<int32_t>::max())/5)
        throw std::runtime_error("Invalid grouped indexed draw size");
    const auto full=instances/nadoc_vr::view_groups::groupSize,remainder=instances%nadoc_vr::view_groups::groupSize;
    return {{{int(indexCount*nadoc_vr::view_groups::groupSize),int(full),0},
             {int(indexCount*remainder),remainder?1:0,int(full*nadoc_vr::view_groups::groupSize)}}};
}
inline bool groupResourcesComplete(const GroupPlan& plan,size_t stride,int64_t vertexBytes,int64_t indexBytes) {
    return plan.eligible && vertexBytes>=0 && indexBytes>=0 &&
        uint64_t(vertexBytes)==plan.expandedVertices*stride && uint64_t(indexBytes)==plan.expandedIndexCount*sizeof(uint32_t);
}
} // namespace nadoc_vr::view_indexed
