#include "view_indexed_mesh.hpp"
#include <array>
#include <cassert>
#include <cstring>
#include <iostream>
#include <stdexcept>
using namespace nadoc_vr::view_indexed;
static int failAllocationAfter=-1;
void* operator new(std::size_t bytes){
    if(failAllocationAfter==0)throw std::bad_alloc();
    if(failAllocationAfter>0)--failAllocationAfter;
    if(auto* value=std::malloc(bytes?bytes:1))return value;
    throw std::bad_alloc();
}
void operator delete(void* value)noexcept{std::free(value);}
void operator delete(void* value,std::size_t)noexcept{std::free(value);}
struct Vertex {std::array<uint32_t,12> words{};};
static_assert(sizeof(Vertex)==48);
static std::vector<Vertex> mesh(size_t count,size_t unique){
    std::vector<Vertex> out(count);
    for(size_t i=0;i<count;++i)for(size_t field=0;field<12;++field)out[i].words[field]=uint32_t((i%unique)*137+field);
    return out;
}
static void exact(const std::vector<Vertex>& source,const Mesh<Vertex>& indexed){
    assert(indexed.plan.eligible && indexed.indices.size()==source.size());
    for(size_t i=0;i<source.size();++i){assert(indexed.indices[i]<indexed.vertices.size());assert(std::memcmp(&source[i],&indexed.vertices[indexed.indices[i]],sizeof(Vertex))==0);}
}
static void groupContracts(const std::vector<Vertex>& source,const Mesh<Vertex>& indexed){
    using nadoc_vr::view_groups::Limits;
    const Limits available{uint64_t(std::numeric_limits<int32_t>::max()),true,true};
    assert(groupsRequested("") && groupsRequested("1") && !groupsRequested("0"));
    bool invalid=false;try{(void)groupsRequested("false");}catch(const std::runtime_error&){invalid=true;}assert(invalid);
    const auto plan=planGroups(indexed.plan,17,sizeof(Vertex),available);
    assert(plan.eligible && plan.expandedVertices==91*8 && plan.expandedIndexCount==420*8);
    const auto expanded=expandGroups(indexed.vertices,indexed.indices,plan);
    assert(expanded.plan.eligible);
    // Reconstruct the actual vertex shader's gl_VertexID-derived logical
    // instance for every emitted index, including nondivisible remainders.
    // This catches a correct geometry set emitted in the wrong blend/tie order.
    for(size_t count:{0U,1U,7U,8U,9U,17U,24U,25U}){
        assert(planGroups(indexed.plan,count,sizeof(Vertex),available).eligible==(count>=8));
        size_t emitted=0;
        for(const auto call:groupDraws(source.size(),count))for(int group=0;group<call.instances;++group)
            for(int k=0;k<call.indexCount;++k){
                const auto index=expanded.indices[size_t(k)];
                const size_t instance=size_t(group)*8+index/indexed.vertices.size()+size_t(call.firstInstance);
                assert(instance==emitted/source.size() && instance<count);
                assert(std::memcmp(&expanded.vertices[index],&source[emitted%source.size()],sizeof(Vertex))==0);
                ++emitted;
            }
        assert(emitted==source.size()*count);
    }
    const auto bytes=plan.derivedBytes;
    assert(planGroups(indexed.plan,8,sizeof(Vertex),available,bytes).eligible);
    assert(!planGroups(indexed.plan,8,sizeof(Vertex),available,bytes-1).eligible);
    assert(!planGroups(indexed.plan,8,sizeof(Vertex),{40,false,true}).eligible);
    assert(!planGroups(indexed.plan,8,sizeof(Vertex),{40,true,false}).eligible);
    assert(!planGroups(indexed.plan,8,sizeof(Vertex),{39,true,true}).eligible);
    assert(planGroups(indexed.plan,8,sizeof(Vertex),{40,true,true}).eligible);
    assert(!planGroups(indexed.plan,size_t(std::numeric_limits<int32_t>::max())/5+1,sizeof(Vertex),available).eligible);
    assert(!planGroups(indexed.plan,8,0,available).eligible);
    assert(!planGroups(indexed.plan,8,257,available).eligible);
    assert(!planGroups(Plan{},8,sizeof(Vertex),available).eligible);
    auto invalidPlan=indexed.plan;invalidPlan.uniqueVertices=invalidPlan.originalVertices+1;
    assert(!planGroups(invalidPlan,8,sizeof(Vertex),available).eligible);
    const auto largest=build(mesh(4095,91));
    assert(planGroups(largest.plan,8,sizeof(Vertex),available).eligible);
    const size_t maxInstances=size_t(std::numeric_limits<int32_t>::max())/5;
    const auto maxCalls=groupDraws(4095,maxInstances);
    assert(uint64_t(maxCalls[0].instances)*8+(maxCalls[1].indexCount/4095)==maxInstances);
    for(size_t bad:{0U,74U,4098U}){bool threw=false;try{(void)groupDraws(bad,8);}catch(const std::runtime_error&){threw=true;}assert(threw);}
    assert(groupResourcesComplete(expanded.plan,sizeof(Vertex),91*8*48,420*8*4));
    assert(!groupResourcesComplete(expanded.plan,sizeof(Vertex),91*8*48-1,420*8*4));
    assert(!groupResourcesComplete(expanded.plan,sizeof(Vertex),91*8*48,420*8*4-1));
    assert(!groupResourcesComplete(expanded.plan,sizeof(Vertex),-1,420*8*4));
    assert(!groupResourcesComplete(GroupPlan{},sizeof(Vertex),0,0));
    auto fails=[](const GroupMesh<Vertex>& result){assert(!result.plan.eligible && result.vertices.empty() && result.indices.empty() && result.plan.derivedBytes==0);};
    fails(expandGroups(indexed.vertices,indexed.indices,plan,bytes-1));
    auto damaged=plan;damaged.expandedVertices-=1;fails(expandGroups(indexed.vertices,indexed.indices,damaged));
    auto badIndices=indexed.indices;badIndices[0]=uint32_t(indexed.vertices.size());fails(expandGroups(indexed.vertices,badIndices,plan));
    const auto originalVertices=indexed.vertices;const auto originalIndices=indexed.indices;
    for(int allocation:{0,1}){
        failAllocationAfter=allocation;const auto result=expandGroups(indexed.vertices,indexed.indices,plan);failAllocationAfter=-1;
        fails(result);assert(std::string_view(result.plan.reason)=="optional_cpu_allocation_failed");
        assert(std::memcmp(indexed.vertices.data(),originalVertices.data(),indexed.vertices.size()*sizeof(Vertex))==0 && indexed.indices==originalIndices);
    }
    // Full record bytes survive replication, including signed zeros/NaNs;
    // no approximate position-only weld is permitted at either preparation step.
    auto attributes=source;attributes[0].words[11]=0x80000000U;attributes[1].words[0]=0x7fc00001U;
    const auto exactBits=build(attributes);const auto bitPlan=planGroups(exactBits.plan,8,sizeof(Vertex),available);
    const auto bitGroups=expandGroups(exactBits.vertices,exactBits.indices,bitPlan);assert(bitGroups.plan.eligible);
    for(size_t k=0;k<bitGroups.indices.size();++k)assert(std::memcmp(&bitGroups.vertices[bitGroups.indices[k]],&attributes[k%attributes.size()],sizeof(Vertex))==0);
}
int main(){
    assert(requested("") && requested("1") && !requested("0"));
    bool invalid=false;try{(void)requested("false");}catch(const std::runtime_error&){invalid=true;}assert(invalid);
    auto source=mesh(420,91);const auto indexed=build(source);exact(source,indexed);
    assert(indexed.vertices.size()==91 && indexed.plan.indexCount==420);
    for(size_t i=0;i<420;++i)assert(indexed.indices[i]==i%91); // deterministic first occurrence and original triangle order
    assert(indexed.plan.derivedBytes<=maxDerivedBytes);
    assert(resourcesComplete(indexed.plan,sizeof(Vertex),91*48,420*4));
    assert(!resourcesComplete(indexed.plan,sizeof(Vertex),90*48,420*4));
    assert(!resourcesComplete(indexed.plan,sizeof(Vertex),91*48,419*4));
    assert(!resourcesComplete(indexed.plan,sizeof(Vertex),-1,420*4));
    assert(!resourcesComplete(Plan{},sizeof(Vertex),0,0));

    // Every attribute bit matters: normal/color/UV differences, signed zero,
    // and distinct NaN payloads must not be collapsed by numeric comparisons.
    std::vector<Vertex> attributes(420);
    for(size_t field=0;field<12;++field)attributes[field+1].words[field]=1;
    attributes[13].words[0]=0x80000000U;
    attributes[14].words[0]=0x7fc00001U;attributes[15].words[0]=0x7fc00002U;
    const auto bits=build(attributes);exact(attributes,bits);assert(bits.vertices.size()==16);
    for(size_t i=0;i<16;++i)assert(bits.indices[i]==i);
    assert(!build(mesh(72,4)).plan.eligible); // grouping retains ownership
    assert(!build(mesh(0,1)).plan.eligible);
    assert(!build(mesh(74,4)).plan.eligible);
    assert(!build(mesh(4098,4)).plan.eligible);
    exact(mesh(4095,91),build(mesh(4095,91)));
    const auto unique=build(mesh(420,420));assert(!unique.plan.eligible && unique.vertices.empty() && unique.indices.empty() && unique.plan.derivedBytes==0);
    const auto budget=source.size()*(sizeof(Vertex)+sizeof(uint32_t));
    assert(!build(source,budget-1).plan.eligible);exact(source,build(source,budget));
    // Optional preparation must fail open at vertex/index allocation and after
    // a partially built lookup, leaving the original vertex stream unchanged.
    const auto original=source;
    for(int allocation:{0,1,2,9}){
        failAllocationAfter=allocation;const auto failed=build(source);failAllocationAfter=-1;
        assert(!failed.plan.eligible && std::string_view(failed.plan.reason)=="optional_cpu_allocation_failed");
        assert(failed.vertices.empty() && failed.indices.empty() && failed.plan.derivedBytes==0);
        assert(std::memcmp(source.data(),original.data(),source.size()*sizeof(Vertex))==0);
    }
    // A view's retained allocations are charged until its exact hard limit.
    size_t remaining=budget*2;
    for(unsigned batch=0;batch<2;++batch){auto item=build(source,remaining);assert(item.plan.eligible);remaining-=item.plan.derivedBytes;}
    assert(remaining==0 && !build(source,remaining).plan.eligible);
    groupContracts(source,indexed);
    std::cout<<"Exact indexed mesh: all attributes/bit patterns, primitive order, bounds, resource sizes and aggregate budget passed\n";
}
