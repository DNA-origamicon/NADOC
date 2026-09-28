#include "dimension_sync.hpp"
#include <iostream>
#include <stdexcept>
int main(int argc,char** argv) {
    if(argc!=2)return 2;
    const std::string path=argv[1];
    auto check=[](bool ok,const char* why){if(!ok)throw std::runtime_error(why);};
    std::ofstream(path+".dimensions-seed")<<"NADOC_DIMENSIONS_1 test 1\nexisting \"Saved dimension\" 1 1 2 3 4 6 3\n";
    nadoc_vr::Dimensions tool;nadoc_vr::DimensionSync sync;
    sync.initialize(path,tool,{10,20,30},.02F,{0,0,-1.3F});
    check(tool.entries.size()==1 && tool.entries[0].key=="existing","Saved dimension missing");
    check(glm::distance(tool.entries[0].points[0],glm::vec3(-.18F,-.36F,-1.84F))<1e-5F,"Incorrect view-nm to normalized model conversion");
    sync.update(tool,{10,20,30},.02F);
    check(!std::filesystem::exists(path+".dimensions-pending"),"Import republished stale state");
    tool.entries[0].visible=false;sync.update(tool,{10,20,30},.02F);
    auto read=[&](){std::ifstream f(path+".dimensions-pending");return std::string(std::istreambuf_iterator<char>(f),{});};
    auto first=read();check(first.find("\"sequence\":1")!=std::string::npos && first.find("\"visible\":false")!=std::string::npos,"Hide did not publish");
    tool.entries[0].visible=true;sync.update(tool,{10,20,30},.02F);
    check(read().find("\"sequence\":1")!=std::string::npos && read().find("\"sequence\":2")!=std::string::npos,"Unacknowledged update lost");
    std::ofstream(path+".dimensions-ack")<<2;
    tool.remove(1);sync.update(tool,{10,20,30},.02F);
    check(read()=="[{\"sequence\":3,\"delete\":\"existing\"}]","Acknowledged operations replayed or deletion lost");
    for(const auto& suffix:{"seed","pending","ack"})std::filesystem::remove(path+".dimensions-"+suffix);
    std::cout<<"Dimension import, normalization, save journal, acknowledgement and delete passed\n";
}
