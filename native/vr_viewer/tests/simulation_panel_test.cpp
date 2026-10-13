#include "simulation_panel.hpp"
#include "representations.hpp"
#include <cassert>
int main(){
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
 nadoc_vr::SimulationSnapshot state;state.version=1;state.engines={{"e:cando","CanDo","",true,true},{"e:namd","NAMD","",true,false}};
 for(int i=0;i<20;++i)state.jobs.push_back({"j:"+std::to_string(i),"24HB production","OCT 12 09:40 / 120 NS",true,i==0});
 state.selected=true;state.mode="trajectory";state.views={{"v:0","Native model","",true,false,"mode","off"},{"v:1","Trajectory","",true,true,"mode","trajectory"}};
 state.hasTrajectory=true;state.trajectory.available=100000;state.trajectory.first=1;state.trajectory.last=100000;state.trajectory.interval=1;state.trajectory.phase=0;
 panel.adopt(state);assert(right.open);assert(panel.focused);assert(menu.bounds().maximum.x<1.1F);
 auto find=[&](const std::string& id){for(const auto& c:panel.controls())if(c.id==id)return c;throw std::runtime_error(id);};
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
 panel.trajectoryUi.digit(5);for(int i=0;i<3;++i)panel.trajectoryUi.digit(0);panel.trajectoryUi.digit(1);
 assert(panel.activate("simulation:local:t:352"));assert(panel.requestedValue==50000);
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
 for(auto rep:{Representation::full,Representation::vdw,Representation::ballstick,Representation::stick,Representation::oxdna,Representation::mrdnaCoarse,Representation::mrdnaFine})assert(simulationRepresentationAllowed(rep));
 for(auto rep:{Representation::cylinders,Representation::beads,Representation::hull,Representation::surface,Representation::surfaceDetail})assert(!simulationRepresentationAllowed(rep));
 return 0;
}
