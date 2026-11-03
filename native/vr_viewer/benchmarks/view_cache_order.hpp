#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace nadoc_vr::benchmark {
// Experimental ordering only: every ordered triangle survives exactly once.
// No welding, winding changes, vertex arithmetic or instance reordering.
inline std::vector<uint32_t> cacheOrder(const std::vector<uint32_t>& indices,size_t vertices) {
 if(!vertices || vertices>4096 || indices.empty() || indices.size()>4096 || indices.size()%3)
  throw std::runtime_error("Invalid bounded cache-order input");
 std::vector<unsigned> remaining(vertices);
 for(auto i:indices){if(i>=vertices)throw std::runtime_error("Invalid cache-order index");++remaining[i];}
 std::vector<bool> done(indices.size()/3),cached(vertices);
 std::vector<uint32_t> out,cache;out.reserve(indices.size());cache.reserve(32);
 for(size_t emitted=0;emitted<done.size();++emitted) {
  size_t best=done.size();double score=-1;
  for(size_t t=0;t<done.size();++t)if(!done[t]){
   double candidate=0;
   for(size_t c=0;c<3;++c){auto i=indices[t*3+c];candidate+=(cached[i]?4.0:0.0)+1.0/remaining[i];}
   if(candidate>score){score=candidate;best=t;}
  }
  done[best]=true;
  for(size_t c=0;c<3;++c){
   auto i=indices[best*3+c];out.push_back(i);--remaining[i];
   cache.erase(std::remove(cache.begin(),cache.end(),i),cache.end());cache.insert(cache.begin(),i);cached[i]=true;
   if(cache.size()>32){cached[cache.back()]=false;cache.pop_back();}
  }
 }
 return out;
}
}
