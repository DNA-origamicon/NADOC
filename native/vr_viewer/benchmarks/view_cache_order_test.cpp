#include "view_cache_order.hpp"
#include <cassert>
#include <set>
#include <iostream>
using Triangle=std::array<uint32_t,3>;
std::multiset<Triangle> triangles(const std::vector<uint32_t>& indices){
 std::multiset<Triangle> out;
 for(size_t i=0;i<indices.size();i+=3)out.insert({indices[i],indices[i+1],indices[i+2]});
 return out;
}
int main(){
 std::vector<uint32_t> grid;
 for(unsigned y=0;y<8;++y)for(unsigned x=0;x<8;++x){
  uint32_t a=y*9+x,b=a+1,c=a+9,d=c+1;
  for(auto i:{a,c,b,b,c,d})grid.push_back(i);
 }
 grid.insert(grid.end(),{0,0,1,0,9,1}); // degenerate and duplicate triangles retained
 const auto out=nadoc_vr::benchmark::cacheOrder(grid,81);
 assert(out.size()==grid.size() && triangles(out)==triangles(grid));
 assert(out==nadoc_vr::benchmark::cacheOrder(grid,81));
 for(auto bad:std::vector<std::vector<uint32_t>>{{},{0,1},{0,1,81}}){
  bool rejected=false;try{nadoc_vr::benchmark::cacheOrder(bad,81);}catch(const std::runtime_error&){rejected=true;}assert(rejected);
 }
 std::cout<<"PASS: exact ordered triangle multiset, duplicates, degenerates, determinism and invalid input rejection\n";
}
