#include "view_volume_panel.hpp"
#include <cassert>
int main(int argc,char** argv) {
    assert(argc==2);
    using namespace nadoc_vr;
    ViewVolumePanel panel;std::array<SidebarMenu,2> menus{SidebarMenu(0),SidebarMenu(1)};
    const std::string path=argv[1];panel.initialize(path);
    {std::ofstream out(path+".volumes-state");out<<"NADOC_VOLUMES_1 0 1\n\"desktop\" \"Desktop box\" 1 0 4 ";for(int i=0;i<8;++i)out<<i<<" 0 0 ";}
    panel.update(menus);assert(panel.connected);assert(panel.entries.size()==1);
    assert(panel.action("volume:toggle",menus,{2,3,4},.01));assert(panel.active);
    auto controls=menus[1].controls();
    for(const auto& action:{"volume:outline:desktop","volume:enabled:desktop","volume:delete:desktop"})
        assert(std::any_of(controls.begin(),controls.end(),[&](const auto& c){return c.action==action&&c.enabled;}));
    int lines=0;panel.draw(glm::mat4(1),{0,0,0},1,{0,0,0},[&](auto,auto,auto){++lines;});assert(lines==12);
    panel.action("volume:enabled:desktop",menus,{2,3,4},.01);
    assert(panel.pending.size()==1);assert(panel.pending[0].second.find("\"value\":true")!=std::string::npos);
    panel.pending.clear();
    panel.action("volume:new:hexagonal",menus,{2,3,4},.01);
    assert(panel.pending[0].second.find("hexagonal")!=std::string::npos);
    assert(panel.pending[0].second.find("\"center\":[2,3,4]")!=std::string::npos);
    panel.pending.clear();panel.entries[0].outline=false;
    lines=0;panel.draw(glm::mat4(1),{0,0,0},1,{0,0,0},[&](auto,auto,auto){++lines;});assert(lines==0);
    panel.entries.resize(17,panel.entries[0]);panel.refresh(menus);
    menus[1].scroll(1);assert(menus[1].offset()==5);
    panel.entries.clear();panel.refresh(menus);assert(menus[1].offset()==0);
    panel.exit(menus);assert(!panel.active&&!menus[1].customTab);
    // A desktop feed arriving mid-drag cannot snap the volume back. Release
    // flushes the final pose even inside the normal 100 ms write interval.
    ViewVolumeRecord record;record.id="desktop";record.name="Round trip";record.center={2,3,4};record.half={10,10,10};record.editable=true;record.rebuild();
    auto state=[&](uint64_t ack,const auto& value) {
        std::ofstream out(path+".volumes-state");out<<"NADOC_VOLUMES_2 "<<ack<<" 1\n\"desktop\" \"Round trip\" 1 1 4 ";
        out<<value.center.x<<' '<<value.center.y<<' '<<value.center.z<<" 10 10 10 0 0 0 1 ";
        for(auto p:value.points)out<<p.x<<' '<<p.y<<' '<<p.z<<' ';
    };
    state(0,record);ViewVolumePanel moving;moving.initialize(path);moving.update(menus);assert(moving.entries[0].editable);
    std::array<HandPose,2> hands{};hands[0].valid=true;hands[0].position=record.center*.01F;
    auto input=[&](bool click,bool press){moving.input(hands,{click,false},{press,false},glm::mat4(1),{0,0,0},.01F,{0,0,0},true,false,[](size_t){});};
    input(true,true);hands[0].position.x+=.1F;input(false,true);
    moving.lastPoll={};moving.update(menus);assert(std::abs(moving.entries[0].center.x-12)<.0001F);
    input(false,false);assert(!moving.pending.empty());assert(moving.pending.back().second.find("transform")!=std::string::npos);
    moving.lastPoll={};moving.update(menus);assert(std::abs(moving.entries[0].center.x-12)<.0001F);
    state(moving.sequence,moving.entries[0]);moving.lastPoll={};moving.update(menus);
    assert(moving.pending.empty());assert(std::abs(moving.entries[0].center.x-12)<.0001F);
    int hot=0;moving.interaction.nearby[0]="desktop";
    moving.draw(glm::mat4(1),{0,0,0},.01F,{0,0,0},[&](auto,auto,glm::vec3 color){if(color.r>.9F&&color.g>.7F)++hot;});assert(hot==12);
    hot=0;moving.interaction.nearby={};
    moving.draw(glm::mat4(1),{0,0,0},.01F,{0,0,0},[&](auto,auto,glm::vec3 color){if(color.r>.9F&&color.g>.7F)++hot;});assert(hot==0);
    std::filesystem::remove(path+".volumes-state");std::filesystem::remove(path+".volumes-pending");
}
