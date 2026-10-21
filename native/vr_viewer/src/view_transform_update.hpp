#pragma once
#include <array>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <istream>
#include <vector>
#include <glm/glm.hpp>

namespace nadoc_vr::view_transforms {
// Updates carry absolute columns, never differences from an intervening frame.
// Reconstruct the original display matrix before the existing normalization.
template<class Instance>
bool read(std::istream& in,const std::vector<Instance>& base,const glm::mat4& normalization,std::vector<Instance>& result) {
 std::array<uint32_t,2> h{};
 if(!in.read(reinterpret_cast<char*>(h.data()),sizeof(h)) || !h[0] || h[0]!=base.size() || (h[1]!=3 && h[1]!=12))return false;
 result=base;
 // Bounded scratch avoids millions of tiny istream reads for large bond batches.
 // Decode in original order and retain the identical normalization arithmetic.
 constexpr size_t blockInstances=1024;
 std::array<float,blockInstances*12> values;
 for(size_t first=0;first<result.size();first+=blockInstances){
  const auto count=std::min(blockInstances,result.size()-first);
  if(!in.read(reinterpret_cast<char*>(values.data()),count*h[1]*sizeof(float)))return false;
  size_t offset=0;
  for(size_t i=first;i<first+count;++i){
   auto& instance=result[i];
   for(unsigned column=h[1]==3?3:0;column<4;++column)for(int row=0;row<3;++row){
    const float value=values[offset++];if(!std::isfinite(value))return false;instance.matrix[column][row]=value;
   }
   instance.matrix=normalization*instance.matrix;
  }
 }
 return true;
}
}
