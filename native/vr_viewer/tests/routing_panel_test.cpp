#include "routing_panel.hpp"
#include <cassert>
#include <filesystem>
#include <unistd.h>
int main() {
    nadoc_vr::SidebarMenu parent(1),popup(1);
    parent.open=true;parent.offsets[parent.selected]=4;
    parent.placement.openDocked({0,1,-1},glm::quat{1,0,0,0});parent.placement.setScale(.45F);
    nadoc_vr::RoutingPanel panel;
    popup.available=[&](const auto& action){return panel.available(action);};
    popup.isActive=[&](const auto& action){return panel.active(action);};
    const auto path=(std::filesystem::temp_directory_path()/("nadoc-routing-test-"+std::to_string(getpid()))).string();
    auto write=[&](int version,int ack,const std::string& title){
        std::ofstream f(path+".routing");f<<"NADOC_ROUTING_1 "<<version<<" "<<ack<<" 1 12 "<<std::quoted(title)<<"\n";
        f<<"\"root\" \"Autoscaffold\" \"\" 1 0\n";
        for(int i=0;i<12;++i)f<<std::quoted("choice-"+std::to_string(i))<<" \"Seamless routing\" \"\" "<<(i!=2)<<" "<<(i==1)<<"\n";
    };
    auto poll=[&]{panel.frames=14;return panel.poll(path,popup,parent);};
    write(1,0,"");assert(poll());assert(!popup.open);assert(panel.activate("routing:root"));assert(!panel.activate("routing:root"));
    write(2,1,"Autoscaffold");assert(poll());assert(popup.open);assert(parent.offset()==4);
    assert(glm::length(popup.placement.position()-parent.placement.worldPoint({0,0,.045F}))<.0001F);
    assert(!panel.available("routing:root"));assert(!panel.available("routing:choice-2"));assert(panel.active("routing:choice-1"));
    for(int page=0;page<3;++page){popup.draw([](glm::vec3,glm::vec3,glm::vec3){},[](nadoc_vr::MenuPanelBounds,glm::vec3){});assert(popup.audit.valid());popup.scroll(1);}
    assert(panel.activate("routing:choice-1"));assert(panel.requestedVersion==2);
    write(3,2,"");assert(poll());assert(!popup.open);assert(parent.open && parent.offset()==4);
    {std::ofstream f(path+".routing");f<<"NADOC_ROUTING_1 4 2 500 0 \"bad\"\n";}
    assert(!poll());assert(panel.version==3);
    std::filesystem::remove(path+".routing");
}
