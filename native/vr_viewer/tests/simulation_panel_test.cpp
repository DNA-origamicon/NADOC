#include "simulation_panel.hpp"
#include <cassert>
int main() {
    nadoc_vr::SidebarMenu menu(0);menu.selected=1;menu.open=true;
    nadoc_vr::SimulationPanel panel;panel.bind(menu);panel.version=1;
    panel.engines={{"e:cando","CanDo","",true,true},{"e:snupi","SNUPI","",true,false}};
    for(int i=0;i<20;++i)panel.jobs.push_back({"j:"+std::to_string(i),"Completed job","",true,false});
    panel.views={{"v:0","Off","",true,true},{"v:1","Predicted shape","",true,false},{"v:2","Unavailable RMSF","",false,false}};
    assert(menu.bounds().maximum.x==.80F);panel.selected=true;assert(menu.bounds().maximum.x==1.56F);
    auto items=menu.controls();assert(items.size()>15);
    menu.focus.begin("sim:scroll:jobs","");menu.navigate({0,-1});assert(panel.jobOffset==7);assert(menu.focus.id=="sim:scroll:jobs");
    menu.navigate({0,-1});menu.navigate({0,-1});menu.navigate({0,-1});assert(panel.jobOffset==14);
    menu.navigate({0,1});assert(panel.jobOffset==7);
    menu.focus.begin("sim:e:cando","");menu.navigate({1,0});assert(menu.focus.id=="sim:e:snupi");
    menu.focus.begin("sim:j:7","");menu.navigate({1,0});assert(menu.focus.id=="sim:v:0");
    menu.navigate({0,-1});assert(menu.focus.id=="sim:v:1");
    assert(panel.activate("simulation:v:1"));assert(panel.requested=="v:1"&&panel.requestedVersion==1);
    assert(!panel.activate("simulation:v:1"));panel.acknowledged=1;assert(panel.activate("simulation:e:snupi"));
}
