#pragma once
#include "sidebar_menu.hpp"
#include "simulation_snapshot.hpp"
namespace nadoc_vr {
// Real job state comes from the document-bound desktop adapter. Disk parsing never
// runs on the XR frame thread; modal edits stay local until an acknowledged action.
class SimulationPanel {
 public:
 using Row=SimulationRow;
 int version=0,acknowledged=0,sequence=0,requestedVersion=0;std::string requested;
 double requestedValue=0;int requestedFirst=1,requestedLast=1,requestedInterval=1;
 bool selected=false,focused=false,overlayOptions=false;std::vector<Row> engines,jobs,views;
 size_t jobOffset=0,viewOffset=0,modeOffset=0;static constexpr size_t page=4;
 SidebarMenu* menu=nullptr;SidebarMenu* adjacent=nullptr;
 SimulationSnapshot snapshot;
 simulation_study::TrajectoryGallery trajectoryUi;
 simulation_study::TrajectoryState trajectory;
 simulation_study::ColourScaleGallery mapper;
 std::future<SimulationSnapshot> pending;double lastPoll=0;std::filesystem::file_time_type stamp{};
 std::string numberId,digits;double numberMin=0,numberMax=0;bool numberReplace=true;
 std::optional<size_t> wheelHand;
 int drag=-1;std::optional<size_t> dragHand;float dragFraction=0;
 static constexpr float shift=.4F,up=.15F;
 bool modal()const{return wheelHand || trajectoryUi.popup || !numberId.empty() || mapper.prompt.active();}
 bool ready()const{return sequence<=acknowledged;}
 void bind(SidebarMenu& target,SidebarMenu* right=nullptr){
  menu=&target;adjacent=right;target.dynamic=[]{return true;};target.dynamicTotal=[this]{return focused?views.size():jobs.size();};target.dynamicOffset=[this]{return focused?viewOffset:jobOffset;};target.dynamicPage=[]{return page;};
  target.dynamicControls=[this](bool){return controls();};target.dynamicBounds=[]{return MenuPanelBounds{{-.515F,-.735F},{1.075F,.735F}};};
  target.dynamicNavigate=[this](glm::vec2 axis){navigate(axis);};target.dynamicScroll=[this](int d){scroll(focused,d);};target.dynamicScrollAt=[this](glm::vec2,int d){scroll(focused,d);};
  target.dynamicScrollTo=[](const std::string&,float){};target.dynamicThumb=[](const std::string&){return MenuPanelBounds{};};
 }
 bool poll(const std::string& path){
  bool changed=false;
  if(pending.valid() && pending.wait_for(std::chrono::seconds(0))==std::future_status::ready){try{adopt(pending.get());changed=true;}catch(const std::exception&){} }
  const double now=menu?menu->animationClock():0;
  if(!path.empty()&&!pending.valid()&&now-lastPoll>.12){lastPoll=now;pending=std::async(std::launch::async,[path]{return SimulationSnapshot::read(path+".simulations");});}
  return changed;
 }
 static std::string active(const std::vector<Row>& rows){for(const auto& r:rows)if(r.active)return r.id;return {};}
 void adopt(SimulationSnapshot next){
  const bool engineChanged=active(next.engines)!=active(engines),jobChanged=active(next.jobs)!=active(jobs);
  if(engineChanged){jobOffset=viewOffset=modeOffset=0;focused=false;}
  if(jobChanged){viewOffset=modeOffset=0;focused=next.selected;}
  if(next.mode!=snapshot.mode || engineChanged || jobChanged){trajectoryUi.close();wheelHand.reset();numberId.clear();mapper.close();dragHand.reset();drag=-1;viewOffset=0;overlayOptions=false;}
  if(!selected&&next.selected)focused=true;
  version=next.version;acknowledged=next.ack;selected=next.selected;
  engines=next.engines;jobs=next.jobs;views=next.views;
  if(engineChanged || jobChanged || next.mode!=snapshot.mode || (!trajectoryUi.popup && !wheelHand && !(sequence>acknowledged && requested=="t:configure")))trajectory=next.trajectory;
  snapshot=std::move(next);

 }
 bool send(const std::string& id,double value=0){if(!ready()||version<1)return false;requested=id;requestedValue=value;requestedFirst=trajectory.first;requestedLast=std::max(1,trajectory.last);requestedInterval=trajectory.interval;requestedVersion=version;++sequence;return true;}
 void scroll(bool options,int direction){auto& offset=options?viewOffset:jobOffset;const size_t count=options?optionsList().size():jobs.size(),step=options?(snapshot.hasScale?3:7):page;if(direction<0)offset=offset>=step?offset-step:0;else if(offset+step<count)offset+=step;}
 std::vector<Row> modes()const{std::vector<Row> out;for(const auto& r:views)if(r.kind=="mode")out.push_back(r);return out;}
 std::vector<Row> optionsList()const{std::vector<Row> out;for(const auto& r:views)if(r.kind!="mode"&&(r.group.empty()||r.group==snapshot.mode))out.push_back(r);return out;}
 std::vector<SidebarControl> controls() const {
  std::vector<SidebarControl> out;
  auto add=[&](std::string id,std::string label,float x,float y,float w,float h,bool enabled=true,bool on=false){out.push_back({"sim:"+id,std::move(label),"","simulation:"+id,{{x+shift,y+up},{x+w+shift,y+h+up}},enabled,on});};
  const bool available=ready()&&!modal();
  for(size_t i=0;i<engines.size();++i)add(engines[i].id,engines[i].label,-.585F+i*.20F,.281F,.17F,engines[i].active?.088F:.062F,available&&engines[i].enabled,engines[i].active);
  if(!focused){
   for(size_t i=jobOffset;i<std::min(jobOffset+page,jobs.size());++i){const auto& r=jobs[i];add(r.id,r.label,-.60F,.085F-(i-jobOffset)*.123F,1.2F,.1F,available&&r.enabled,r.active);out.back().section=r.detail;}
   add("local:prev","PREV",-.6F,-.455F,.2F,.055F,available&&jobOffset>0);add("local:next","NEXT",.4F,-.455F,.2F,.055F,available&&jobOffset+page<jobs.size());return out;
  }
  add("local:back","< JOBS",-.60F,.174F,.23F,.065F,!modal());add("local:frame","FRAME RESULT",.37F,.174F,.23F,.065F,!modal());
  const auto ms=modes();for(size_t i=modeOffset;i<std::min(modeOffset+size_t(8),ms.size());++i){const auto& r=ms[i];add(r.id,r.label,-.6F,.021F-(i-modeOffset)*.06095F,.529F,.05405F,available&&r.enabled,r.active);}
  if(ms.size()>8){add("local:modesprev","<",-.6F,-.51F,.10F,.04F,available&&modeOffset>0);add("local:modesnext",">",-.48F,-.51F,.10F,.04F,available&&modeOffset+8<ms.size());}
  if(snapshot.hasTrajectory){add("local:transport","PLAYBACK",-.05F,.043F,.31F,.043F,available,!overlayOptions);add("local:overlays","OVERLAYS",.28F,.043F,.32F,.043F,available,overlayOptions);}
  if(snapshot.hasTrajectory&&!overlayOptions){
   auto ui=trajectoryUi;if(modal())ui.popup=0;
   for(const auto& c:ui.controls(trajectory,true))add("local:t:"+std::to_string(c.id),c.label,c.x,c.y,c.w,c.h,available&&(c.enabled||(c.id==305&&trajectory.playing))&&trajectory.available>0,c.selected);
   if(trajectoryUi.popup)for(const auto& c:trajectoryUi.controls(trajectory,true))add("local:t:"+std::to_string(c.id),c.label,c.x,c.y,c.w,c.h,c.enabled,c.selected);
  }else{
   const auto opts=optionsList();const size_t n=snapshot.hasScale?3:7;
   for(size_t i=viewOffset;i<std::min(viewOffset+n,opts.size());++i){const auto& r=opts[i];std::string text=r.label;if(r.kind=="number")text+=" "+std::to_string(r.value);
    add(r.id,text,-.05F,(snapshot.hasScale?-.263F:-.04F)-(i-viewOffset)*.055F,.65F,.047F,available&&r.enabled,r.active);}
   if(opts.size()>n){add("local:prev","<",-.05F,-.45F,.14F,.042F,available&&viewOffset>0);add("local:next","MORE >",.42F,-.45F,.18F,.042F,available&&viewOffset+n<opts.size());}
   if(snapshot.hasScale){for(int id:{200,201}){auto b=mapper.bar(true,snapshot.scale,id);add("local:c:"+std::to_string(id),id==200?"MIN":"MAX",b.x,b.y,b.z,b.w,available);}
    add("local:palette",simulation_study::paletteNames[snapshot.scale.palette],-.034F,-.19F,.415F,.043F,available);
    add("c:reset","RESET",.398F,-.19F,.186F,.043F,available);}
  }
  if(!numberId.empty()){
   const std::array<std::string,12> keys{"7","8","9","4","5","6","1","2","3","-","0","."};
   for(size_t i=0;i<12;++i)add("local:key:"+keys[i],keys[i],-.04F+(i%3)*.21F,-.11F-(i/3)*.06F,.195F,.052F);
   add("local:erase","ERASE",-.04F,-.36F,.18F,.045F);add("local:cancel","CANCEL",.15F,-.36F,.19F,.045F);add("local:apply","APPLY",.35F,-.36F,.23F,.045F,numberValid());
  }
  if(mapper.prompt.active())add("local:cancel","CANCEL",-.04F,-.42F,.22F,.045F);
  return out;
 }
 bool numberValid()const{try{size_t n;double v=std::stod(digits,&n);return n==digits.size()&&std::isfinite(v)&&v>=numberMin&&v<=numberMax;}catch(...){return false;}}
 bool activate(const std::string& action){
  if(!action.starts_with("simulation:"))return false;
  const auto id=action.substr(11);
  if(id=="local:transport"||id=="local:overlays"){overlayOptions=id=="local:overlays";viewOffset=0;return false;}
  if(id=="local:back"){focused=false;return false;}if(id=="local:prev"||id=="local:next"){scroll(focused,id.ends_with("prev")?-1:1);return false;}
  if(id=="local:modesprev"){modeOffset=modeOffset>8?modeOffset-8:0;return false;}if(id=="local:modesnext"){modeOffset+=8;return false;}
  if(id=="local:cancel"){numberId.clear();mapper.close();trajectoryUi.close();return false;}
  if(id=="local:erase"){if(!digits.empty())digits.pop_back();numberReplace=false;return false;}
  if(id.starts_with("local:key:")){if(numberReplace){digits.clear();numberReplace=false;}if(digits.size()<14)digits+=id.substr(10);return false;}
  if(id=="local:apply"){if(!numberValid())return false;auto key=numberId;numberId.clear();return send(key,std::stod(digits));}
  if(id=="local:palette"){mapper.open(snapshot.scale);return false;}
  if(id.starts_with("local:c:")){drag=std::stoi(id.substr(8));return false;}
  if(id.starts_with("local:t:")){
   const int key=std::stoi(id.substr(8));
   if(key==311){drag=311;return false;}
   if(key==303){if(trajectory.count()>=500){trajectoryUi.popup=2;return false;}return send("t:load");}
   if(key==362){trajectoryUi.close();return send("t:load");}
   if(key==304)return send("t:cancel");
   if(key==305)return send("t:play");
   if(key==307||key==308)return send("t:seek",std::clamp(trajectory.index+(key==307?-1:1),0,trajectory.loadedCount()-1));
   if(key==310)return send("t:smooth"); // native Full currently advances exact sampled frames
   const int field=trajectoryUi.field;trajectoryUi.action(trajectory,key);
   if(key==352&&!trajectoryUi.popup)return field==306?send("t:seek",trajectory.index):send("t:configure");
   if(key==309||key==361)return send("t:configure");
   return false;
  }
  for(const auto& r:views)if(r.id==id&&r.kind=="number"){numberId=id;digits=std::to_string(r.value);numberReplace=true;numberMin=r.minimum;numberMax=r.maximum;return false;}
  return send(id);
 }
 void navigate(glm::vec2 axis){auto cs=menu->controls(false);auto at=std::find_if(cs.begin(),cs.end(),[&](const auto& c){return c.id==menu->focus.id;});if(at==cs.end())return;
  const auto p=(at->bounds.minimum+at->bounds.maximum)*.5F;const bool horizontal=std::abs(axis.x)>std::abs(axis.y);float best=1e9;const SidebarControl* next=nullptr;
  for(const auto& c:cs){if(!c.enabled||c.id==at->id)continue;auto d=(c.bounds.minimum+c.bounds.maximum)*.5F-p;const float a=horizontal?d.x:d.y;if(a*(horizontal?axis.x:axis.y)<=0)continue;float cost=std::abs(a)+4*std::abs(horizontal?d.y:d.x);if(cost<best){best=cost;next=&c;}}if(next)menu->focus.id=next->id;
 }
 template<class Publish> void rangeInput(const std::array<HandPose,2>& hands,const std::array<bool,2>& clicked,const std::array<bool,2>& held,std::array<bool,2>& blocked,float dt,Publish publish){
  auto& wheels=trajectoryUi.wheels;wheels.hover=-1;
  const bool visible=menu->open&&menu->tab().key=="dynamics"&&focused&&snapshot.hasTrajectory&&!overlayOptions;
  if(wheelHand){
   const size_t h=*wheelHand;blocked[h]=true;
   auto p=menu->placement.rayPanelLocalPoint(hands[h],{-100,-100},{100,100});
   if(visible&&held[h]&&hands[h].valid&&p)wheels.move(trajectory,p->y-up,dt);
   else {const bool changed=wheels.changed;wheels.stop();wheelHand.reset();if(changed&&send("t:configure"))publish();}
   return;
  }
  if(!visible||modal()||!ready()||trajectory.phase==1||trajectory.available<1)return;
  for(size_t h=0;h<2;++h){if(blocked[h])continue;
   auto p=menu->placement.rayPanelLocalPoint(hands[h],{-100,-100},{100,100});if(!p)continue;
   for(int id=300;id<=302;++id){
    const auto hit=thumbwheelHit(wheels.shape(),wheels.center(id)+glm::vec3(shift,up,0),menu->placement,hands[h]);
    if(!hit)continue;
    wheels.hover=id;
    if(clicked[h]){wheelHand=h;wheels.begin(id,p->y-up);blocked[h]=true;return;}
   }
  }
 }
 template<class Publish> void input(const std::array<HandPose,2>& hands,const std::array<bool,2>& clicked,const std::array<bool,2>& held,std::array<bool,2>& blocked,float dt,Publish publish){
  rangeInput(hands,clicked,held,blocked,dt,publish);
  if(wheelHand)return;
  if(!menu->open||menu->tab().key!="dynamics"){drag=-1;dragHand.reset();mapper.close();return;}
  mapper.handleHover=-1;
  for(size_t h=0;h<2;++h){if(blocked[h]&&!dragHand)continue;if(dragHand&&*dragHand!=h)continue;
   auto p=menu->placement.rayPanelLocalPoint(hands[h],{-100,-100},{100,100});
   if(!p||!hands[h].valid){if(dragHand){dragHand.reset();drag=-1;}continue;}
   int scaleHit=-1;float nearest=1e9F;
   if(snapshot.hasScale&&!modal())for(int id:{200,201}){auto b=mapper.bar(true,snapshot.scale,id);auto q=glm::vec2(*p)-glm::vec2(shift,up);if(q.x>=b.x&&q.x<=b.x+b.z&&q.y>=b.y&&q.y<=b.y+b.w){float d=std::abs(q.x-b.x-b.z*.5F);if(d<nearest){nearest=d;scaleHit=id;}}}
   if(scaleHit>=0)mapper.handleHover=scaleHit;
   if(!dragHand&&clicked[h]&&scaleHit>=0){drag=scaleHit;dragHand=h;}
   if(!dragHand&&clicked[h]){auto c=menu->hit(hands[h]);if(c&&c->enabled){if(c->id=="sim:local:t:311")drag=311;else if(c->id=="sim:local:c:200")drag=200;else if(c->id=="sim:local:c:201")drag=201;else continue;dragHand=h;}}
   if(!dragHand)continue;
   blocked[h]=true;glm::vec2 local=glm::vec2(*p)-glm::vec2(shift,up);
   if(drag==311){dragFraction=std::clamp(simulation_study::TrajectoryGallery::fraction(true,{local,0}),0.F,1.F);trajectory.seek(dragFraction);}
   else {dragFraction=std::clamp(mapper.fraction(true,local),0.F,1.F);simulation_study::scaleBound(snapshot.scale,drag,dragFraction);mapper.drag=drag;}
   if(!held[h]){bool sent=drag==311?send("t:seek",trajectory.index):send(drag==200?"c:low":"c:high",snapshot.scaleMinimum+(snapshot.scaleMaximum-snapshot.scaleMinimum)*(drag==200?snapshot.scale.low:snapshot.scale.high));dragHand.reset();drag=-1;mapper.drag=-1;if(sent)publish();}
  }
 }
 template<class Pulse,class Publish> bool pad(bool pressed,glm::vec2 axis,const HandPose& hand,double now,Pulse pulse,Publish publish){if(!mapper.prompt.active())return false;int before=snapshot.scale.palette;
  mapper.prompt.update(pressed,axis,hand,now,[&](float strength){++mapper.pulses;pulse(strength);});if(!mapper.prompt.active()&&before!=snapshot.scale.palette){if(send("c:palette",snapshot.scale.palette))publish();}return true;}
 template<class Stream> void describe(Stream& out)const {
  out<<",\"simulation_menu\":{\"version\":"<<version<<",\"acknowledged\":"<<acknowledged<<",\"sequence\":"<<sequence<<",\"focused\":"<<(focused?"true":"false")<<",\"palette_open\":"<<(mapper.prompt.active()?"true":"false")<<",\"palette\":"<<snapshot.scale.palette<<",\"palette_hover\":"<<(mapper.prompt.hovered()?int(*mapper.prompt.hovered()):-1)<<",\"palette_pulses\":"<<mapper.pulses<<",\"palette_center\":["<<mapper.prompt.worldPoint({0,0,0}).x<<","<<mapper.prompt.worldPoint({0,0,0}).y<<","<<mapper.prompt.worldPoint({0,0,0}).z<<"]"<<",\"palette_right\":["<<(mapper.prompt.worldPoint({1,0,0})-mapper.prompt.worldPoint({0,0,0})).x<<","<<(mapper.prompt.worldPoint({1,0,0})-mapper.prompt.worldPoint({0,0,0})).y<<","<<(mapper.prompt.worldPoint({1,0,0})-mapper.prompt.worldPoint({0,0,0})).z<<"]"<<",\"palette_up\":["<<(mapper.prompt.worldPoint({0,1,0})-mapper.prompt.worldPoint({0,0,0})).x<<","<<(mapper.prompt.worldPoint({0,1,0})-mapper.prompt.worldPoint({0,0,0})).y<<","<<(mapper.prompt.worldPoint({0,1,0})-mapper.prompt.worldPoint({0,0,0})).z<<"]"<<",\"mode\":"<<std::quoted(snapshot.mode)<<",\"popup\":"<<trajectoryUi.popup<<",\"phase\":"<<std::quoted(snapshot.phase)<<",\"frame\":"<<trajectory.sourceFrame()<<",\"available\":"<<trajectory.available<<",\"count\":"<<trajectory.count()<<",\"first\":"<<trajectory.first<<",\"last\":"<<trajectory.last<<",\"interval\":"<<trajectory.interval<<",\"range_wheel\":"<<trajectoryUi.wheels.active<<",\"range_hover\":"<<trajectoryUi.wheels.hover<<",\"range_step\":"<<trajectoryUi.wheels.step<<",\"playing\":"<<(trajectory.playing?"true":"false")<<"}";
 }
 template<class UI> void draw(UI& ui)const;
};
}
#include "simulation_panel_draw.hpp"
