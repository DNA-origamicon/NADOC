#include "routing_panel.hpp"
#include <cassert>
#include <iostream>
#include <fstream>
int main(int argc,char** argv) {
    using namespace nadoc_vr;
    SidebarMenu launcher(0);
    const auto launchControls=launcher.controls();
    const auto fileTab=std::find_if(launchControls.begin(),launchControls.end(),[](const auto& c){return c.id=="tab:file";});
    assert(fileTab!=launchControls.end()&&launcher.activate(*fileTab)=="routing:file-open");
    launcher.available=[](const auto&){return false;};assert(launcher.activate(*fileTab).empty());
    SidebarMenu table(1);table.open=true;
    table.customTab=SidebarTab{1,"file-browser","Open / Save File",{}};
    table.customTab->rows.push_back({"routing-help","Workspace","","",{}});
    for(const auto* action:{"new","assembly","open","save","close"})table.customTab->rows.push_back({std::string("routing:file-")+action,action,"",std::string("routing:file-")+action,{}});
    for(int i=0;i<14;++i)table.customTab->rows.push_back({"routing:file-entry-"+std::to_string(i),"A long file name that must stay in its own column.nadoc","Part|2026-11-23|123.4 KB","routing:file-entry-"+std::to_string(i),{}});
    table.available=[](const auto& action){return action!="routing:file-assembly";};
    for(int page=0;page<3;++page){
        table.draw([](auto,auto,auto){},[](auto,auto){});
        if(!table.audit.valid()){std::cerr<<table.audit.summary()<<'\n';return 1;}
        const auto visible=table.controls();
        assert(std::count_if(visible.begin(),visible.end(),[](const auto& c){return fileTableEntry(c.id);})==(page==2?2:6));
        assert(std::any_of(visible.begin(),visible.end(),[](const auto& c){return c.id=="routing:file-new";}));
        assert(std::any_of(visible.begin(),visible.end(),[](const auto& c){return c.id=="routing:file-assembly"&&!c.enabled;}));
        for(const auto& c:visible){const auto center=(c.bounds.minimum+c.bounds.maximum)*.5F;
            HandPose hand{true,false,table.placement.worldPoint({center,.5F}),{1,0,0,0}};
            assert(table.hit(hand)&&table.hit(hand)->id==c.id);
        }
        table.scroll(1);
    }
    assert(table.offset()==12);table.scroll(-1);assert(table.offset()==6);
    table.customTab->rows.clear();table.offsets[table.selected]=0;
    table.draw([](auto,auto,auto){},[](auto,auto){});assert(table.audit.valid()&&table.total()==0);
    FileHoverFeedback hover;
    assert(hover.enter("a"));assert(!hover.enter("a"));assert(hover.enter("b"));
    assert(!hover.enter(""));assert(hover.enter("a"));
    SidebarMenu menu(1);menu.open=true;
    menu.placement.openDocked({0,0,0},{1,0,0,0});menu.placement.setScale(kFileKeyboardScale);
    SidebarTab tab{1,"file-keyboard","Filename keyboard",{}};
    tab.rows.push_back({"routing-help","test_part.nadoc","","",{}});
    for(const auto* label:{"Cancel","Create"})tab.rows.push_back({std::string("routing:")+label,label,"",std::string("routing:")+label,{}});
    const auto keys=fileKeyboardKeys();assert(keys.size()==42);
    std::string qwerty,home,bottom;
    for(const auto& key:keys) {
        if(key.row==1)qwerty+=key.key;
        if(key.row==2)home+=key.key;
        if(key.row==3 && key.key.size()==1)bottom+=key.key;
        const auto label=key.key=="delete"?"Backspace":key.key=="shift"?"Shift":key.key=="underscore"?"_":key.key=="space"?"Space":key.key=="dot"?".":key.key=="dash"?"-":key.key;
        tab.rows.push_back({"routing:file-key-"+key.key,label,"","routing:file-key-"+key.key,{}});
    }
    assert(qwerty=="qwertyuiop" && home=="asdfghjkl" && bottom=="zxcvbnm");
    menu.customTab=tab;
    menu.draw([](auto,auto,auto){},[](auto,auto){});
    if(!menu.audit.valid()){std::cerr<<menu.audit.summary()<<'\n';return 1;}
    for(const auto& c:menu.controls()) {
        const auto center=(c.bounds.minimum+c.bounds.maximum)*.5F;
        HandPose hand{true,false,menu.placement.worldPoint({center,.5F}),{1,0,0,0}};
        assert(menu.hit(hand) && menu.hit(hand)->id==c.id);
    }
    if(argc>1 && std::string(argv[1])=="--targets") {
        for(const auto& c:menu.controls())if(c.id.starts_with("routing:file-key-")) {
            const auto center=menu.placement.worldPoint({(c.bounds.minimum+c.bounds.maximum)*.5F,0.F});
            std::cout<<c.id.substr(17)<<" "<<center.x<<" "<<center.y<<"\n";
        }
        return 0;
    }
    if(argc>1) {
        std::ifstream in(argv[1]);std::string key;float x,y,z,qx,qy,qz,qw;size_t hits=0,total=0;
        while(in>>key>>x>>y>>z>>qx>>qy>>qz>>qw) {
            HandPose hand{true,false,{x,y,z},{qw,qx,qy,qz}};
            const auto hit=menu.hit(hand);++total;
            if(hit && hit->id=="routing:file-key-"+key)++hits;
        }
        std::cout<<hits<<" "<<total<<'\n';assert(total>0);return double(hits)/total>=.95?0:2;
    }
}
