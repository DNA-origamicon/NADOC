#include "simulation_panel.hpp"
#include "feature_log_panel.hpp"
#include <cassert>
#include <iostream>
using namespace nadoc_vr;
int main(){
    SidebarMenu menu(0);SimulationPanel jobs;jobs.bind(menu);
    FeatureLogPanel history;history.bind(menu);history.version=10;menu.open=true;
    for(int i=0;i<20;++i)history.rows.push_back({"r:"+std::to_string(i),i?"F"+std::to_string(i)+": Bend":"F0 Initial",true,i==0,i>0,i>0,i>0,false});
    assert(menu.dynamicActive()&&menu.pageRows()==6&&menu.total()==20);
    auto get=[&](const std::string& id){auto controls=menu.controls(false);auto it=std::find_if(controls.begin(),controls.end(),[&](const auto& c){return c.id==id;});assert(it!=controls.end());return *it;};
    assert(!get("history:delete:0").enabled && get("history:edit:1").enabled);
    assert(get("history:row:1").action=="history:r:1");
    assert(get("history:delete:1").action=="history:a:1:delete");
    for(int page=0;page<4;++page){menu.draw([](glm::vec3,glm::vec3,glm::vec3){},[](MenuPanelBounds,glm::vec3){});if(!menu.audit.valid())std::cerr<<menu.audit.summary();assert(menu.audit.valid());history.scroll(6);}
    assert(history.offset==14);history.scroll(-100);assert(history.offset==0);
    assert(history.scrub(.326F-.13F*4,false).empty());assert(history.preview==4 && history.sequence==0);
    assert(history.scrub(.326F-.13F*4,true)=="history:r:4");assert(history.sequence==0);
    assert(history.activate("history:r:4"));assert(history.sequence==1&&history.requestedVersion==10);
    assert(!history.activate("history:a:1:delete"));history.acknowledged=1;
    assert(history.scrub(.326F,false).empty());assert(history.scrub(.326F,true).empty());
    history.scrub(.066F,false);history.version++;assert(history.scrub(.066F,true).empty());
    menu.historyScrubCancel();history.scrub(.066F,false);menu.historyScrubCancel();assert(history.preview==-1);
    history.busy=true;assert(!history.activate("history:r:2"));history.busy=false;
    menu.focus.begin("history:row:5","");menu.navigate({0,-1});assert(menu.focus.id=="history:row:6"&&history.offset==1);
    menu.selected=1;jobs.version=1;assert(menu.dynamicActive()&&menu.pageRows()==7&&menu.bounds().maximum.x==.80F);
    menu.selected=0;history.rows.clear();history.offset=0;assert(!get("history:scrub").enabled);assert(history.scrub(0,true).empty());
    std::cout<<"History layout, row actions, bounds, scrub-on-release, stale drag, busy state and simulation routing passed\n";
}
