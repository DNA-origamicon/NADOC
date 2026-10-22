#pragma once
#include <glm/glm.hpp>
#include <cstring>
#include <cstddef>
#include <new>
#include <cstdlib>
#include <stdexcept>
#include <string_view>
#include <vector>

namespace nadoc_vr::view_compact {
struct Vertex {glm::vec3 p,normal;};
static_assert(sizeof(Vertex)==24 && offsetof(Vertex,normal)==12);
inline constexpr size_t maxBytes=1024*1024;
inline bool requestedFromEnvironment(){
 const char* value=std::getenv("NADOC_VR_COMPACT_VIEW_VERTICES");
 if(!value || std::string_view(value)=="1")return true;
 if(std::string_view(value)=="0")return false;
 throw std::runtime_error("NADOC_VR_COMPACT_VIEW_VERTICES requires 0 or 1");
}
// Only constant, opaque, untextured attributes. Geometry bytes and triangle
// order stay intact; GL generic attributes supply the identical color and UV.
template<class V> std::vector<Vertex> pack(const std::vector<V>& source,size_t remaining=maxBytes){
 if(source.empty() || source.size()>remaining/sizeof(Vertex) ||
    source.front().color.a!=1 || !(source.front().uv.x<0))return {};
 for(const auto& v:source)if(std::memcmp(&v.color,&source.front().color,sizeof(v.color)) ||
                              std::memcmp(&v.uv,&source.front().uv,sizeof(v.uv)))return {};
 try {
  std::vector<Vertex> out(source.size());
  if(out.capacity()>remaining/sizeof(Vertex))return {};
  for(size_t i=0;i<source.size();++i){
   std::memcpy(&out[i].p,&source[i].p,sizeof(glm::vec3));
   std::memcpy(&out[i].normal,&source[i].normal,sizeof(glm::vec3));
  }
  return out;
 }catch(const std::bad_alloc&){return {};}
}
}
