#pragma once
namespace nadoc_vr {
template<class UI> void SimulationPanel::draw(UI& ui)const{
 const size_t begin=ui.vertices.size();const glm::vec3 ink(.92F,.96F,1),muted(.64F,.66F,.68F),cyan(.38F,.82F,.93F),face(.085F,.13F,.17F);
 auto text=[&](std::string s,float x,float y,float width,float scale,glm::vec3 color,float z=.018F){const auto fit=boundedMenuStrokeText(s,width,scale,.0026F);ui.text(fit.text,x,y,fit.scale,color,z);};
 auto jobDetail=[&](std::string s,float x,float y,float width,float scale,float z){
  const bool done=s.ends_with(" / DONE");if(done)s.resize(s.size()-7);
  text(s,x,y,width-(done?.035F:0.F),scale,muted,z);
  if(done){float a=x+width-.027F;glm::vec3 p{a,y-.007F,z},q{a+.008F,y-.015F,z},r{a+.026F,y+.008F,z};
   auto stroke=[&](glm::vec3 u,glm::vec3 v){glm::vec3 n=glm::normalize(glm::vec3(-(v-u).y,(v-u).x,0))*.002F;ui.triangle(u-n,v-n,v+n,cyan);ui.triangle(u-n,v+n,u+n,cyan);};stroke(p,q);stroke(q,r);}
 };
 ui.rounded(-.633F,-.557F,1.266F,.834F,.014F,{.24F,.35F,.41F},.004F);ui.rounded(-.63F,-.554F,1.26F,.828F,.014F,face,.006F);
 // Curved tab shoulders merge into the selected engine's panel surface.
 auto tab=[&](size_t i){const auto& r=engines[i];float x=-.60F+i*.20F,y=.276F,top=y+(r.active?.103F:.077F);std::vector<glm::vec3> points{{x-.016F,y,.009F}};
  auto curve=[&](glm::vec2 control,glm::vec2 end){const glm::vec2 start(points.back());for(int n=1;n<=8;++n){float t=n/8.F;points.push_back({(1-t)*(1-t)*start+2*(1-t)*t*control+t*t*end,.009F});}};
  curve({x+.012F,y},{x+.012F,y+.023F});points.push_back({x+.012F,top-.022F,.009F});curve({x+.012F,top},{x+.035F,top});points.push_back({x+.165F,top,.009F});curve({x+.188F,top},{x+.188F,top-.022F});points.push_back({x+.188F,y+.023F,.009F});curve({x+.188F,y},{x+.216F,y});
  for(size_t n=0;n<points.size();++n)ui.triangle({x+.10F,y+.028F,.009F},points[n],points[(n+1)%points.size()],r.active?face:glm::vec3(.055F,.078F,.105F));
  if(r.active)ui.rect(x-.012F,.265F,.224F,.016F,face,.011F);
  text(r.label,x+.026F,y+(r.active?.064F:.05F),.15F,.0034F,r.active?ink:muted,.014F);
 };
 for(size_t i=0;i<engines.size();++i)if(!engines[i].active)tab(i);
 for(size_t i=0;i<engines.size();++i)if(engines[i].active)tab(i);
 text("SIMULATION JOBS / FULL",-.60F,.444F,1.2F,.004F,cyan);
 if(focused){for(const auto& j:jobs)if(j.active){text(j.label,-.34F,.220F,.69F,.004F,ink);jobDetail(j.detail,-.34F,.179F,.69F,.0026F,.018F);break;}
  ui.rect(-.6F,.132F,1.2F,.002F,{.23F,.34F,.40F},.011F);text("VISUALIZATIONS",-.60F,.111F,.53F,.0033F,cyan);
  text(snapshot.hasTrajectory?"TRAJECTORY":"OPTIONS",-.05F,.100F,.65F,.0032F,cyan);
  if(snapshot.hasTrajectory&&!overlayOptions)trajectoryUi.draw(ui,trajectory,true,menu->hovered=="sim:local:t:311"?311:-1,true);
  else if(snapshot.hasScale){mapper.draw(ui,true,snapshot.scale,2);ui.rounded(-.046F,-.019F,.64F,.035F,.003F,{.055F,.10F,.145F},.022F);text(snapshot.scaleTitle,-.033F,-.007F,.60F,.003F,cyan,.024F);
   auto val=[](float v){std::ostringstream out;out<<std::setprecision(4)<<v;return out.str();};ui.rect(-.04F,-.133F,.63F,.04F,{.055F,.10F,.145F},.022F);
   text("MIN "+val(snapshot.scaleMinimum+(snapshot.scaleMaximum-snapshot.scaleMinimum)*snapshot.scale.low),-.034F,-.110F,.29F,.0028F,ink,.024F);
   text("MAX "+val(snapshot.scaleMinimum+(snapshot.scaleMaximum-snapshot.scaleMinimum)*snapshot.scale.high),.29F,-.110F,.29F,.0028F,ink,.024F);
  }
 }
 auto cs=controls();for(const auto& c:cs){if(c.id.starts_with("sim:e:") || (c.id=="sim:local:t:300"||c.id=="sim:local:t:301"||c.id=="sim:local:t:302") || c.id=="sim:local:t:311" || c.id=="sim:local:c:200" || c.id=="sim:local:c:201" || (trajectoryUi.popup&&c.id.starts_with("sim:local:t:3")&&std::stoi(c.id.substr(12))>=340) || c.id.starts_with("sim:local:key:") || c.id=="sim:local:erase" || c.id=="sim:local:apply" || c.id=="sim:local:cancel")continue;
  auto b=c.bounds; b.minimum-=glm::vec2(shift,up);b.maximum-=glm::vec2(shift,up);const auto size=b.maximum-b.minimum;bool hot=menu->hovered==c.id||(menu->focus.active&&menu->focus.id==c.id);
  const glm::vec3 color=c.active?glm::vec3(.08F,.31F,.36F):hot?glm::vec3(.20F,.32F,.39F):glm::vec3(.12F,.17F,.22F);ui.bevel(b.minimum.x,b.minimum.y,size.x,size.y,.008F,.012F,hot?.027F:.020F,.004F,color);
  text(c.label,b.minimum.x+.008F,b.maximum.y-.014F,size.x-.016F,.0035F,c.enabled?ink:muted,hot?.030F:.024F);
  if(c.id.starts_with("sim:j:"))jobDetail(c.section,b.minimum.x+.012F,b.minimum.y+.028F,size.x-.024F,.0028F,.024F);
 }
 // Real phase progress remains visible throughout preparation and errors.
 const auto& ps=snapshot.progress;const auto label=ps.empty()?(snapshot.hasTrajectory?snapshot.message:version?"FULL REPRESENTATION":"WAITING FOR DESKTOP"):ps.back().label;
 text(label,-.60F,-.490F,1.2F,.0028F,cyan,.033F);ui.rect(-.60F,-.536F,1.20F,.010F,{.18F,.25F,.30F},.022F);
 if(!ps.empty()){const auto& p=ps.back();if(p.fraction>=0)ui.rect(-.60F,-.536F,1.2F*std::clamp(p.fraction,0.F,1.F),.010F,cyan,.024F);
  else if(p.busy){float f=std::fmod(float(menu->animationClock())*.45F,1.F);ui.rect(-.60F+f*.95F,-.536F,.25F,.010F,cyan,.024F);}}
 if(trajectoryUi.popup){trajectoryUi.drawPopup(ui,trajectory);for(const auto& c:trajectoryUi.controls(trajectory,true)){ui.bevel(c.x,c.y,c.w,c.h,.006F,.063F,.070F,.004F,{.12F,.22F,.28F});text(c.label,c.x+.008F,c.y+c.h-.012F,c.w-.016F,.0033F,c.enabled?ink:muted,.073F);}}
 if(!numberId.empty()){ui.rounded(-.06F,-.44F,.67F,.547F,.016F,{.075F,.115F,.16F},.06F);text("EXACT VALUE",-.035F,.08F,.6F,.004F,cyan,.075F);text(digits,-.035F,.015F,.6F,.005F,ink,.075F);
  for(const auto& c:cs)if(c.id.starts_with("sim:local:key:")||c.id=="sim:local:erase"||c.id=="sim:local:apply"||c.id=="sim:local:cancel"){auto b=c.bounds;b.minimum-=glm::vec2(shift,up);b.maximum-=glm::vec2(shift,up);ui.rect(b.minimum.x,b.minimum.y,b.maximum.x-b.minimum.x,b.maximum.y-b.minimum.y,{.12F,.22F,.28F},.070F);text(c.label,b.minimum.x+.009F,b.maximum.y-.014F,b.maximum.x-b.minimum.x-.018F,.0035F,c.enabled?ink:muted,.073F);}}
 if(mapper.prompt.active())text("CHOOSE ON LEFT TOUCHPAD",-.037F,.032F,.61F,.0026F,ink,.061F);
 for(size_t i=begin;i<ui.vertices.size();++i)ui.vertices[i].position+=glm::vec3(shift,up,0);
}
}
