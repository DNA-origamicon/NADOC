#include "view_compact_vertices.hpp"
#include <cassert>
#include <iostream>
struct V {glm::vec3 p;glm::vec4 color;glm::vec2 uv;glm::vec3 normal;};
int main(){
 using namespace nadoc_vr::view_compact;
 const V vertex{{-0.0F,2,3},{.3F,.4F,.5F,1},{-1,-1},{.1F,-0.0F,1}};
 std::vector<V> source(24,vertex);
 auto packed=pack(source);assert(packed.size()==source.size());
 for(size_t i=0;i<source.size();++i){assert(!std::memcmp(&packed[i].p,&source[i].p,12));assert(!std::memcmp(&packed[i].normal,&source[i].normal,12));}
 assert(pack(source,24*24-1).empty());assert(pack(source,24*24).size()==24);
 source[3].color.r=.31F;assert(pack(source).empty());source[3]=vertex;
 source[3].uv.y=0;assert(pack(source).empty());source[3]=vertex;
 for(auto& v:source){v.color.a=.5F;}assert(pack(source).empty());
 source.assign(24,vertex);for(auto& v:source)v.uv.x=0;assert(pack(source).empty());
 source.assign(24,vertex);for(auto& v:source)v.color.r=0;source[1].color.r=-0.0F;assert(pack(source).empty());
 assert(pack(std::vector<V>{}).empty());
 std::cout<<"Exact geometry bytes, attribute eligibility and allocation bounds passed\n";
}
