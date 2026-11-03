#include "view_transform_update.hpp"
#include <glm/gtc/matrix_transform.hpp>
#include <sstream>
#include <cassert>
#include <cstring>
#include <chrono>
#include <algorithm>
#include <iostream>
#include <limits>
struct Instance {glm::mat4 matrix;glm::vec4 color;};
// Independent original decoder is the exact-value oracle and timing baseline.
static bool scalarRead(std::istream& in,const std::vector<Instance>& base,const glm::mat4& normalization,std::vector<Instance>& result){
 uint32_t h[2];if(!in.read((char*)h,8)||h[0]!=base.size()||(h[1]!=3&&h[1]!=12))return false;
 result=base;
 for(auto& instance:result){for(unsigned c=h[1]==3?3:0;c<4;c++){float xyz[3];if(!in.read((char*)xyz,12))return false;for(int r=0;r<3;r++){if(!std::isfinite(xyz[r]))return false;instance.matrix[c][r]=xyz[r];}}instance.matrix=normalization*instance.matrix;}
 return true;
}
static void largeParity(bool benchmark){
 const auto normalization=glm::translate(glm::mat4(1),glm::vec3(.3F,-.7F,.1F))*glm::scale(glm::mat4(1),glm::vec3(.137F));
 for(uint32_t count:benchmark?std::vector<uint32_t>{2000,500000}:std::vector<uint32_t>{1023,1024,1025,4097})for(uint32_t mode:{3U,12U}){
  std::vector<Instance> base(count,{glm::mat4(1),{.2F,.4F,.6F,1}}),expected,actual;
  std::vector<float> values(size_t(count)*mode);
  for(size_t i=0;i<values.size();i++)values[i]=i%19==0?-0.F:float(int(i%97)-48)*.123F;
  const uint32_t header[2]={count,mode};std::string bytes((const char*)header,8);bytes.append((const char*)values.data(),values.size()*4);
  std::vector<double> scalar,blocked;
  for(int trial=0;trial<(benchmark?8:1);trial++){
   // Alternate ordering to avoid consistently favoring warm caches.
   for(bool reference:trial%2?std::vector<bool>{false,true}:std::vector<bool>{true,false}){
    std::istringstream input(bytes);const auto start=std::chrono::steady_clock::now();
    assert(reference?scalarRead(input,base,normalization,expected):nadoc_vr::view_transforms::read(input,base,normalization,actual));
    const auto ms=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
    if(trial)(reference?scalar:blocked).push_back(ms);
   }
   assert(actual.size()==expected.size()&&std::memcmp(actual.data(),expected.data(),count*sizeof(Instance))==0);
  }
  if(benchmark){std::sort(scalar.begin(),scalar.end());std::sort(blocked.begin(),blocked.end());std::cout<<"{\"instances\":"<<count<<",\"components\":"<<mode<<",\"scalar_median_ms\":"<<scalar[3]<<",\"current_median_ms\":"<<blocked[3]<<",\"exact_parity\":true}\n";}
  else{
   std::istringstream truncated(bytes.substr(0,bytes.size()-1));assert(!nadoc_vr::view_transforms::read(truncated,base,normalization,actual));
   float invalid=std::numeric_limits<float>::quiet_NaN();std::memcpy(bytes.data()+bytes.size()-4,&invalid,4);
   std::istringstream nonfinite(bytes);assert(!nadoc_vr::view_transforms::read(nonfinite,base,normalization,actual));
  }
 }
}
int main(int argc,char** argv){
 if(argc==2&&std::string(argv[1])=="--benchmark"){largeParity(true);return 0;}
 largeParity(false);
 const glm::mat4 normalization=glm::translate(glm::mat4(1),glm::vec3(.3F,.1F,-.2F))*glm::scale(glm::mat4(1),glm::vec3(.137F))*glm::translate(glm::mat4(1),glm::vec3(-4,2,8));
 std::vector<Instance> base{{glm::mat4(1),{.1F,.2F,.3F,1}}};base[0].matrix[3]=glm::vec4(4,5,6,1);
 for(uint32_t mode:{3U,12U}){
  auto expected=base;std::ostringstream bytes;const uint32_t h[2]={1,mode};bytes.write((const char*)h,sizeof(h));
  for(unsigned c=mode==3?3:0;c<4;++c)for(int r=0;r<3;++r){float v=(c*3+r)*.123F;bytes.write((const char*)&v,4);expected[0].matrix[c][r]=v;}
  expected[0].matrix=normalization*expected[0].matrix;
  std::istringstream input(bytes.str());std::vector<Instance> actual;
  assert(nadoc_vr::view_transforms::read(input,base,normalization,actual));
  assert(actual.size()==expected.size() && std::memcmp(actual.data(),expected.data(),sizeof(Instance))==0);
  std::istringstream truncated(bytes.str().substr(0,bytes.str().size()-1));assert(!nadoc_vr::view_transforms::read(truncated,base,normalization,actual));
  // No accumulation: applying the same packet after an unrelated frame is exact.
  actual[0].matrix=glm::mat4(99);std::istringstream repeat(bytes.str());assert(nadoc_vr::view_transforms::read(repeat,base,normalization,actual));assert(std::memcmp(actual.data(),expected.data(),sizeof(Instance))==0);
 }
 for(uint32_t mode:{0U,4U,16U}){const uint32_t h[2]={1,mode};std::string bytes((const char*)h,sizeof(h));std::istringstream input(bytes);std::vector<Instance> out;assert(!nadoc_vr::view_transforms::read(input,base,normalization,out));}
}
