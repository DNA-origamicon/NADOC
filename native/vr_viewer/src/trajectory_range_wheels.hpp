#pragma once
#include "thumbwheel_mesh.hpp"

namespace simulation_study {
// Smallest gallery cylinder, independent of the number of source frames.
// Travel drives physical rotation; measured speed selects integer detent gain.
class TrajectoryRangeWheels {
 public:
    int active=-1,hover=-1,step=1;
    bool changed=false;
    float lastY=0,travel=0,rotation=0,speed=0;
    static constexpr float notch=.012F;
    static bool field(int id){return id>=300 && id<=302;}
    static nadoc_vr::ThumbwheelShape shape(){return nadoc_vr::thumbwheelPreset(10,.20F);}
    static glm::vec3 center(int id){return {float(id-300)*.214F,-.050F,.012F};}
    static int gain(float velocity,int available){
        return available>=1000 && velocity>=.50F?100:available>=100 && velocity>=.12F?10:1;
    }
    void begin(int id,float y){active=id;lastY=y;travel=rotation=speed=0;step=1;changed=false;}
    void stop(){active=-1;travel=speed=0;step=1;}
    template<class State> int move(State& t,float y,float dt){
        if(active<0 || !std::isfinite(y))return 0;
        const float dy=y-lastY;lastY=y;
        // Tracking gaps are a new anchor, never a fast flick.
        if(!std::isfinite(dt)||dt<=0 || dt>.1F || std::abs(dy)>.15F){travel=speed=0;return 0;}
        if(dy*travel<0){travel=0;speed=0;}
        speed+=(std::abs(dy)/dt-speed)*(1-std::exp(-dt/.035F));
        step=gain(speed,t.available);travel+=dy;rotation+=dy;
        const int ticks=int(travel/notch);travel-=ticks*notch;
        int& value=active==300?t.first:active==301?t.last:t.interval;
        const int low=active==301?t.first:1,high=active==300?t.last:t.available;
        const int before=value;
        value=int(std::clamp(static_cast<long long>(value)+static_cast<long long>(ticks)*step,
                            static_cast<long long>(low),static_cast<long long>(std::max(low,high))));
        if(value!=before){changed=true;t.invalidate();}
        if((dy<0&&value==low)||(dy>0&&value==high))travel=0;
        return value-before;
    }
    template<class UI,class State> void draw(UI& ui,const State& t)const{
        const glm::vec3 ink(.92F,.96F,1),muted(.57F,.68F,.77F),cyan(.38F,.82F,.93F),amber(1,.75F,.25F);
        for(int id=300;id<=302;++id){
            const auto c=center(id);const auto s=shape();const bool hot=active==id || hover==id;
            ui.rounded(c.x-.05F,c.y-s.halfOpening()-.004F,.10F,2*s.halfOpening()+.008F,.004F,{.012F,.018F,.026F},.011F);
            nadoc_vr::thumbwheelMesh(s,active==id?rotation/notch:0,c,[&](auto a,auto b,auto d,auto normal){
                float light=.32F+.68F*std::max(0.F,glm::dot(normal,glm::normalize(glm::vec3(-.4F,.7F,1.F))));
                ui.triangle(a,b,d,(t.phase==1?muted*.45F:hot?amber:cyan)*light);
            });
            const std::string value=std::to_string(id==300?t.first:id==301?t.last:t.interval);
            ui.text(id==300?"START":id==301?"END":"EVERY",c.x+.06F,c.y+.023F,.0025F,muted,.015F);
            ui.text(value,c.x+.06F,c.y+.002F,std::min(.0034F,.091F/(6*value.size())),t.phase==1?muted:ink,.015F);
            if(hot)ui.text(active==id?"X"+std::to_string(step):"DRAG",c.x+.06F,c.y-.024F,.0022F,amber,.016F);
        }
    }
};
}
