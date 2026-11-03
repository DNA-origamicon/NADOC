#include "simulation_panel.hpp"
#include "representations.hpp"
#include <cassert>
#include <iostream>
int main(int argc,char** argv){
 // Version 3 carries loop state; version 2 remains readable as Loop Off.
 auto wire=std::filesystem::temp_directory_path()/"nadoc-loop-snapshot-test";
 for(int version:{2,3}){
  {std::ofstream out(wire);out<<"NADOC_SIMULATIONS_"<<version<<" 1 0 0 0 0 1 \"traj\"\n1\n100 7 21 5 3 2 \"ready\" 1 0 1 \"Ready\""<<(version==3?" 1":"")<<"\n0\n0\n";}
  const auto parsed=nadoc_vr::SimulationSnapshot::read(wire.string());
  assert(parsed.trajectory.loop==(version==3));assert(parsed.trajectory.sourceFrame()==17);
 }
 std::filesystem::remove(wire);

 nadoc_vr::SidebarMenu menu(0);for(size_t i=0;i<menu.tabs.size();++i)if(nadoc_vr::kSidebarTabs[menu.tabs[i]].key=="dynamics")menu.selected=i;menu.open=true;
 nadoc_vr::SidebarMenu right(1);right.open=true;
 nadoc_vr::SimulationPanel panel;panel.bind(menu,&right);
 double clock=0;menu.animationClock=[&]{return clock;};
 auto settle=[&]{panel.syncScale();clock+=.23;panel.syncScale();};
 menu.placement.setScale(.45F);
 nadoc_vr::SimulationSnapshot state;state.version=1;state.engines={{"e:cando","CanDo","",true,true},{"e:namd","NAMD","",true,false}};
 for(int i=0;i<20;++i)state.jobs.push_back({"j:"+std::to_string(i),"24HB production","OCT 12 09:40 / 120 NS",true,i==0});
 state.selected=true;state.mode="trajectory";state.views={{"v:0","Native model","",true,false,"mode","off"},{"v:1","Trajectory","",true,true,"mode","trajectory"}};
 state.hasTrajectory=true;state.trajectory.available=100000;state.trajectory.first=1;state.trajectory.last=100000;state.trajectory.interval=1;state.trajectory.phase=0;
 if(argc==2 && (std::string(argv[1])=="--target-dimensions" || std::string(argv[1])=="--target-layout")){
  state.trajectory.phase=2;panel.adopt(state);
  std::cout<<"[";bool first=true;
  const bool layout=std::string(argv[1])=="--target-layout";
  for(const auto& c:menu.controls())if(layout || (c.enabled && c.id.starts_with("sim:"))){
   if(!first)std::cout<<",";first=false;
   const auto size=(c.bounds.maximum-c.bounds.minimum)*.45F;
   std::cout<<"{\"id\":"<<std::quoted(c.id)<<",\"label\":"<<std::quoted(c.label)
            <<",\"width_m\":"<<size.x<<",\"height_m\":"<<size.y;
   if(layout){const auto center=(c.bounds.minimum+c.bounds.maximum)*.225F;
    std::cout<<",\"center_m\":["<<center.x<<","<<center.y<<"],\"enabled\":"<<(c.enabled?"true":"false");}
   std::cout<<"}";
  }
  std::cout<<"]\n";return 0;
 }
 panel.adopt(state);assert(right.open);assert(panel.focused);assert(menu.bounds().maximum.x<1.1F);
 assert(std::abs(menu.placement.scale()-.45F)<1.e-6F); // No jump on adoption.
 clock+=.11;panel.syncScale();assert(std::abs(menu.placement.scale()-.675F)<1.e-6F);
 // Render placement and the production ray path agree at an intermediate size.
 menu.placement.openDocked({0,0,0},glm::quat(1,0,0,0));
 for(const auto& c:panel.controls())if(c.id=="sim:local:back"){
  const auto center=(c.bounds.minimum+c.bounds.maximum)*.5F;
  nadoc_vr::HandPose ray;ray.valid=true;ray.orientation=glm::quat(1,0,0,0);
  ray.position=menu.placement.worldPoint({center.x,center.y,.3F});
  const auto hit=menu.hit(ray);assert(hit && hit->id==c.id);
 }
 // Reverse halfway through expansion without a discontinuity.
 panel.activate("simulation:local:back");assert(std::abs(menu.placement.scale()-.675F)<1.e-6F);
 settle();assert(std::abs(menu.placement.scale()-.45F)<1.e-6F);
 panel.focused=true;settle();assert(std::abs(menu.placement.scale()-.90F)<1.e-6F);
 panel.adopt(state);settle();assert(std::abs(menu.placement.scale()-.90F)<1.e-6F);
 menu.placement.setScale(.78F); // A manual resize survives returning to the job list.
 panel.activate("simulation:local:back");settle();assert(std::abs(menu.placement.scale()-.39F)<1.e-6F);
 panel.focused=true;settle();assert(std::abs(menu.placement.scale()-.78F)<1.e-6F);
 const auto dynamics=menu.selected;
 menu.selected=0;assert(menu.tab().key!="dynamics");settle();
 assert(std::abs(menu.placement.scale()-.39F)<1.e-6F);
 menu.selected=dynamics;settle();assert(std::abs(menu.placement.scale()-.78F)<1.e-6F);
 menu.placement.setScale(.25F);panel.activate("simulation:local:back");settle();
 assert(std::abs(menu.placement.scale()-.25F)<1.e-6F);
 panel.focused=true;settle();assert(std::abs(menu.placement.scale()-.50F)<1.e-6F);
 menu.open=false;settle();menu.open=true;settle();
 assert(std::abs(menu.placement.scale()-.50F)<1.e-6F);
 panel.activate("simulation:local:back");settle();menu.placement.setScale(8.F);
 panel.focused=true;settle();panel.activate("simulation:local:back");settle();
 assert(std::abs(menu.placement.scale()-8.F)<1.e-6F);
 menu.placement.setScale(.45F);panel.focused=true;settle();
 // A grip resize during animation is retained through completion and reversal.
 panel.activate("simulation:local:back");settle();panel.focused=true;panel.syncScale();
 clock+=.055;panel.syncScale();menu.placement.setScale(menu.placement.scale()*1.2F);
 settle();assert(std::abs(menu.placement.scale()-1.08F)<1.e-6F);
 panel.activate("simulation:local:back");settle();assert(std::abs(menu.placement.scale()-.54F)<1.e-6F);
 menu.placement.setScale(.45F);panel.focused=true;settle();
 auto find=[&](const std::string& id){for(const auto& c:panel.controls())if(c.id==id)return c;throw std::runtime_error(id);};
 // Original local geometry is retained; only the placement scales.
 assert(std::abs(find("sim:local:t:309").bounds.maximum.y-find("sim:local:t:309").bounds.minimum.y-.034F)<1.e-6F);
 assert(!find("sim:local:t:305").enabled);assert(find("sim:local:t:303").enabled);
 assert(!panel.activate("simulation:local:t:303"));assert(panel.trajectoryUi.popup==2);assert(!find("sim:e:namd").enabled);
 assert(!panel.activate("simulation:local:t:360"));assert(panel.trajectoryUi.popup==0);assert(panel.sequence==0);
 panel.activate("simulation:local:t:303");assert(panel.activate("simulation:local:t:362"));assert(panel.requested=="t:load");assert(!panel.send("e:namd"));
 state.ack=panel.sequence;state.trajectory.phase=2;state.trajectory.loadedFirst=1;state.trajectory.loadedLast=100000;state.trajectory.loadedInterval=1;panel.adopt(state);
 assert(find("sim:local:t:312").label=="LOOP OFF");
 assert(panel.activate("simulation:local:t:312"));assert(panel.requested=="t:loop");
 state.ack=panel.sequence;state.trajectory.loop=true;panel.adopt(state);
 assert(find("sim:local:t:312").active && find("sim:local:t:312").label=="LOOP ON");
 assert(find("sim:local:t:305").enabled);assert(panel.activate("simulation:local:t:308"));assert(panel.requested=="t:seek"&&panel.requestedValue==1);
 state.ack=panel.sequence;panel.adopt(state);panel.activate("simulation:local:t:306");
 menu.placement.openDocked({0,0,0},glm::quat(1,0,0,0));
 for(int digit=0;digit<=9;++digit){
  auto key=find("sim:local:t:"+std::to_string(340+digit));
  auto center=(key.bounds.minimum+key.bounds.maximum)*.5F;
  nadoc_vr::HandPose ray;ray.valid=true;ray.orientation=glm::quat(1,0,0,0);
  ray.position=menu.placement.worldPoint({center.x,center.y,.3F});
  const auto hit=menu.hit(ray);assert(hit && hit->id==key.id && hit->enabled);
 }
 // Aim at the rendered popup face, from both upward and downward ray angles.
 auto clickFace=[&](const std::string& id,float slope){
  const auto key=find(id);const auto center=(key.bounds.minimum+key.bounds.maximum)*.5F;
  const auto target=menu.placement.worldPoint({center.x,center.y,.070F});
  nadoc_vr::HandPose ray;ray.valid=true;
  ray.position=menu.placement.worldPoint({center.x,center.y+slope*.3F,.370F});
  ray.orientation=glm::rotation(glm::vec3(0,0,-1),glm::normalize(target-ray.position));
  const auto hit=menu.hit(ray);assert(hit && hit->id==id && hit->enabled);
  return panel.activate(menu.activate(*hit));
 };
 for(float slope:{-1.F,0.F,1.F}){
  const int before=panel.sequence;
  clickFace("sim:local:t:345",slope);
  clickFace("sim:local:t:353",slope);
  assert(!panel.modal() && panel.sequence==before && panel.trajectory.index==0);
  panel.activate("simulation:local:t:306");
 }
 panel.trajectoryUi.digit(5);for(int i=0;i<3;++i)panel.trajectoryUi.digit(0);panel.trajectoryUi.digit(1);
 assert(clickFace("sim:local:t:352",1.F));assert(panel.requestedValue==50000);
 state.ack=panel.sequence;state.trajectory.phase=1;state.trajectory.buffering=true;state.trajectory.index=50000;state.trajectory.playing=true;panel.adopt(state);
 assert(panel.trajectory.hasFrame());assert(find("sim:local:t:306").label=="FRAME 50001 / 100000");
 assert(!find("sim:local:t:311").enabled);assert(find("sim:local:t:305").enabled); // Pause remains available while buffering.
 state.trajectory.buffering=false;state.trajectory.playing=false;panel.adopt(state);
 assert(!panel.trajectory.hasFrame());assert(find("sim:local:t:306").label=="FRAME -- / LOAD TO ENABLE");
 // Drive the real ray/cylinder path; heartbeat snapshots cannot erase a draft.
 state.trajectory.phase=0;panel.adopt(state);
 menu.placement.openDocked({0,0,0},glm::quat(1,0,0,0));
 std::array<nadoc_vr::HandPose,2> hands{};
 auto point=simulation_study::TrajectoryRangeWheels::center(300)+glm::vec3(panel.shift,panel.up,.3F);
 hands[1].valid=true;hands[1].orientation=glm::quat(1,0,0,0);
 hands[1].position=menu.placement.worldPoint(point);
 std::array<bool,2> clicks{false,true},held{false,true},blocked{};int publishes=0;
 auto input=[&]{blocked.fill(false);panel.input(hands,clicks,held,blocked,1.F/90,[&]{++publishes;});clicks.fill(false);};
 input();assert(panel.wheelHand && !panel.trajectoryUi.popup);assert(blocked[1]);
 for(int i=1;i<=90;++i){hands[1].position=menu.placement.worldPoint(point+glm::vec3(0,.013F*i/90,0));input();panel.adopt(state);}
 assert(panel.trajectory.first==2 && panel.trajectory.phase==0 && publishes==0);
 held[1]=false;input();assert(!panel.wheelHand && publishes==1 && panel.requested=="t:configure");
 assert(panel.requestedFirst==2 && panel.requestedLast==100000 && panel.requestedInterval==1);
 panel.adopt(state);assert(panel.trajectory.first==2); // stale ack after release
 state.ack=panel.sequence;state.trajectory.first=2;panel.adopt(state);assert(panel.ready());
 // Hidden controls and loading never acquire the wheel.
 panel.focused=false;clicks[1]=held[1]=true;input();assert(!panel.wheelHand);
 panel.focused=true;state.trajectory.phase=1;panel.adopt(state);clicks[1]=true;input();assert(!panel.wheelHand);
 // Generic numeric overlays share the same raised-face routing and must own
 // pixels covered by their disabled background option rows.
 state.trajectory.phase=2;state.ack=panel.sequence;state.hasTrajectory=false;
 state.views.push_back({"n:frame","Frame","",true,false,"number","",10,1,100});
 panel.adopt(state);
 for(float slope:{-1.F,0.F,1.F}){
  panel.activate("simulation:n:frame");
  const int before=panel.sequence;
  clickFace("sim:local:key:5",slope);
  clickFace("sim:local:cancel",slope);
  assert(!panel.modal() && panel.sequence==before);
 }
 panel.activate("simulation:n:frame");clickFace("sim:local:key:5",1.F);
 assert(clickFace("sim:local:apply",-1.F));
 assert(!panel.modal() && panel.requested=="n:frame" && panel.requestedValue==5);
 for(auto rep:{Representation::full,Representation::vdw,Representation::ballstick,Representation::stick,Representation::oxdna,Representation::mrdnaCoarse,Representation::mrdnaFine})assert(simulationRepresentationAllowed(rep));
 for(auto rep:{Representation::cylinders,Representation::beads,Representation::hull,Representation::surface,Representation::surfaceDetail})assert(!simulationRepresentationAllowed(rep));
 return 0;
}
