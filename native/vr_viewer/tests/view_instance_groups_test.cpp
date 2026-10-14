#include "view_instance_groups.hpp"
#include "view_opaque_shader.hpp"
#include <cassert>
#include <iostream>
using namespace nadoc_vr::view_groups;
int main() {
    assert(requested("") && !requested("0") && requested("1"));
    bool invalid=false;try{requested("8");}catch(const std::runtime_error&){invalid=true;}assert(invalid);
    const Limits limits{10000000,true,true};
    assert(plan(36,154202,48,limits).eligible);assert(plan(18,154202,48,limits).eligible);
    assert(plan(72,154202,48,limits).expandedBytes==72*8*48);
    for(auto p:{plan(73,154202,48,limits),plan(0,16,48,limits),plan(3,7,48,limits),plan(36,154202,48,{100,true,true}),plan(36,154202,48,{10000000,false,true}),plan(36,154202,48,{10000000,true,false}),plan(36,154202,48,limits,16),plan(36,154202,std::numeric_limits<size_t>::max(),limits),plan(36,size_t(std::numeric_limits<int32_t>::max()),48,limits)})assert(!p.eligible);
    const std::vector<int> base{12,11,10,22,21,20};const auto expanded=expand(base);assert(base.size()==6 && expanded.size()==48);
    for(size_t i=0;i<expanded.size();++i)assert(expanded[i]==base[i%base.size()]);
    for(size_t n:{size_t(0),size_t(1),size_t(7),size_t(8),size_t(9),size_t(16),size_t(17),size_t(154202)}) {
        size_t expected=0;
        for(auto call:draws(base.size(),n))for(int gpuInstance=0;gpuInstance<call.instances;++gpuInstance)for(int vertex=0;vertex<call.vertices;++vertex){
            const auto logical=size_t(gpuInstance)*8+size_t(vertex)/base.size()+call.firstInstance;
            assert(logical<n && logical==expected/base.size());assert(expanded[vertex]==base[expected%base.size()]);++expected;
        }
        assert(expected==n*base.size());
    }
    const auto source=vertexShader(nadoc_vr::view_opaque::vertexSource);
    assert(source.find("gl_InstanceID*8+gl_VertexID/uGroupBaseVertices+uGroupFirstInstance")!=std::string::npos);
    assert(source.find("gl_Position=vp*point;")!=std::string::npos && source.find("vNormal=transpose(inverse(mat3(worldModel*m)))*normal;")!=std::string::npos);
    bool badSource=false;try{vertexShader("void main(){}");}catch(const std::runtime_error&){badSource=true;}assert(badSource);
    std::cout<<"Group8 bounds, bounded mesh allocation, exact source sequence and remainder indexing passed\n";
}
