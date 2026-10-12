#pragma once
#include <algorithm>
#include "trajectory_range_wheels.hpp"
#include <glm/glm.hpp>
#include <cmath>
#include <string>
#include <vector>

namespace simulation_study {
struct StudyControl {int id;float x,y,w,h;std::string label;bool selected=false,enabled=true;};
struct TrajectoryState {
    int available=100000;
    // Matches TRAJ_FRAME_CONFIRM in frontend/src/ui/md_trajectory_presentation.js.
    static constexpr int confirmFrames=500;
    int first=1,last=4000,interval=20,index=0,phase=0; // 0 unprepared, 1 loading, 2 ready
    int loadedFirst=1,loadedLast=4000,loadedInterval=20;
    float progress=0,elapsed=0;bool playing=false,smooth=true,buffering=false;
    bool hasFrame() const {return phase==2 || buffering;}
    bool valid() const {return first>=1 && last<=available && first<=last && interval>=1 && interval<=available;}
    int count() const {return valid()?(last-first)/interval+1:0;}
    int loadedCount() const {return (loadedLast-loadedFirst)/loadedInterval+1;}
    int sourceFrame() const {return loadedFirst+index*loadedInterval;}
    int finalFrame() const {return loadedFirst+(loadedCount()-1)*loadedInterval;}
    void invalidate(){buffering=false;phase=0;playing=false;progress=elapsed=0;index=0;}
    void start(){if(!valid())return;buffering=false;loadedFirst=first;loadedLast=last;loadedInterval=interval;index=0;phase=1;playing=false;progress=elapsed=0;}
    void step(int amount){if(phase==2){playing=false;index=std::clamp(index+amount,0,loadedCount()-1);}}
    void seek(float f){if(phase==2){playing=false;index=int(std::round(std::clamp(f,0.F,1.F)*(loadedCount()-1)));}}
    void seekSource(int frame){if(phase==2){playing=false;index=std::clamp(int(std::round(float(frame-loadedFirst)/loadedInterval)),0,loadedCount()-1);}}
    void update(float dt){
        if(phase==1){progress=std::min(1.F,progress+dt/3.F);if(progress>=1){phase=2;playing=false;}}
        if(phase==2 && playing){elapsed+=dt;if(elapsed>=.125F){elapsed=0;if(index<loadedCount()-1)++index;else playing=false;}}
    }
};
class TrajectoryGallery {
 public:
    // Popup 1: exact integer entry. Popup 2: requested frame-count confirmation.
    TrajectoryRangeWheels wheels;
    int popup=0,field=0;std::string digits;bool replace=true;int drag=-1;
    void close(){wheels.stop();popup=0;drag=-1;digits.clear();}
    static bool isMode(int m){return m==8 || m==9;}
    int number() const {if(digits.empty() || digits.size()>9)return -1;return std::stoi(digits);}
    bool numberValid(const TrajectoryState& t) const {
        const int n=number();return n>=1 && n<=t.available && (field!=306 || (n>=t.loadedFirst && n<=t.finalFrame()));
    }
    void edit(TrajectoryState& t,int id){
        field=id;popup=1;replace=true;t.playing=false;
        digits=std::to_string(id==300?t.first:id==301?t.last:id==302?t.interval:t.sourceFrame());
    }
    void digit(int value){if(popup!=1)return;if(replace){digits.clear();replace=false;}if(digits.size()<9)digits+=char('0'+value);}
    void backspace(){if(popup!=1)return;replace=false;if(!digits.empty())digits.pop_back();}
    void apply(TrajectoryState& t){
        if(!numberValid(t))return;
        const int n=number();
        if(field==306)t.seekSource(n);
        else {int& target=field==300?t.first:field==301?t.last:t.interval;if(target!=n){target=n;t.invalidate();}}
        close();
    }
    void load(TrajectoryState& t){if(!t.valid())return;t.playing=false;if(t.count()>=TrajectoryState::confirmFrames)popup=2;else t.start();}
    void action(TrajectoryState& t,int id){
        if(id>=340 && id<=349){digit(id-340);return;}
        if(id==350){digits.clear();replace=false;return;}
        if(id==351){backspace();return;}
        if(id==352){apply(t);return;}
        if(id==353 || id==360){close();return;}
        if(id==361){t.interval=std::max(1,int(std::ceil(float(t.last-t.first+1)/200)));t.invalidate();close();return;}
        if(id==362){t.start();close();return;}
        if(id==306){edit(t,id);return;}
        if(id==303)load(t);
        if(id==304)t.invalidate();
        if(id==305 && t.phase==2){if(t.index==t.loadedCount()-1)t.index=0;t.playing=!t.playing;}
        if(id==307)t.step(-1);
        if(id==308)t.step(1);
        if(id==309){t.first=1;t.last=t.available;t.interval=1;t.invalidate();}
        if(id==310)t.smooth=!t.smooth;
    }
    static glm::vec4 scrubber(bool detailed){return detailed?glm::vec4(-.025F,-.310F,.405F,.06F):glm::vec4(-.025F,-.314F,.600F,.055F);}
    static float fraction(bool detailed,glm::vec3 p){auto b=scrubber(detailed);return (p.x-b.x)/b.z;}
    std::vector<StudyControl> controls(const TrajectoryState& t,bool detailed) const {
        if(popup==1){
            std::vector<StudyControl> c;
            const int keys[12]={7,8,9,4,5,6,1,2,3,-1,0,-2};
            for(int i=0;i<12;++i)c.push_back({keys[i]>=0?340+keys[i]:keys[i]==-1?350:351,-.04F+(i%3)*.212F,-.112F-(i/3)*.060F,.195F,.052F,keys[i]>=0?std::to_string(keys[i]):keys[i]==-1?"CLEAR":"< ERASE"});
            c.push_back({353,-.04F,-.420F,.300F,.055F,"CANCEL"});
            c.push_back({352,.281F,-.420F,.300F,.055F,"APPLY",false,numberValid(t)});return c;
        }
        if(popup==2)return {{360,-.04F,-.225F,.625F,.053F,"EDIT RANGE / CANCEL"},
            {361,-.04F,-.296F,.625F,.053F,"USE ABOUT 200 FRAMES"},
            {362,-.04F,-.390F,.625F,.067F,"LOAD "+std::to_string(t.count())+" FRAMES"}};
        const bool ready=t.phase==2,editable=t.phase!=1;
        std::vector<StudyControl> c{{300,-.05F,-.083F,.100F,.068F,"START "+std::to_string(t.first),false,editable},
            {301,.164F,-.083F,.100F,.068F,"END "+std::to_string(t.last),false,editable},
            {302,.378F,-.083F,.100F,.068F,"EVERY "+std::to_string(t.interval),false,editable},
            {309,.395F,-.113F,.205F,.034F,"ALL FRAMES",false,editable}};
        c.push_back({t.phase==1?304:303,detailed?.398F:-.05F,-.184F,detailed?.202F:.65F,.055F,
            t.phase==1?"CANCEL LOAD":ready?"RELOAD":"LOAD",false,t.valid()});
        if(detailed)c.push_back({310,-.05F,-.184F,.432F,.055F,t.smooth?"SMOOTH: ON":"SMOOTH: OFF",t.smooth});
        c.push_back({306,-.05F,-.245F,.65F,.044F,t.hasFrame()?"FRAME "+std::to_string(t.sourceFrame())+" / "+std::to_string(t.finalFrame()):"FRAME -- / LOAD TO ENABLE",false,ready});
        const auto b=scrubber(detailed);c.push_back({311,b.x,b.y,b.z,b.w,"SCRUBBER",false,ready});
        if(detailed){
            c.push_back({305,.423F,-.347F,.177F,.087F,t.playing?"PAUSE":"PLAY",t.playing,ready && t.loadedCount()>1});
            c.push_back({307,-.05F,-.422F,.313F,.060F,"< PREVIOUS",false,ready && t.index>0});
            c.push_back({308,.280F,-.422F,.320F,.060F,"NEXT >",false,ready && t.index<t.loadedCount()-1});
        }else{
            c.push_back({307,-.05F,-.419F,.130F,.058F,"< PREV",false,ready && t.index>0});
            c.push_back({305,.092F,-.419F,.155F,.058F,t.playing?"PAUSE":"PLAY",t.playing,ready && t.loadedCount()>1});
            c.push_back({308,.259F,-.419F,.125F,.058F,"NEXT >",false,ready && t.index<t.loadedCount()-1});
            c.push_back({310,.396F,-.419F,.204F,.058F,t.smooth?"SMOOTH ON":"SMOOTH OFF",t.smooth});
        }
        return c;
    }
    template<class UI> void draw(UI& ui,const TrajectoryState& t,bool detailed,int hover,bool live=false) const {
        const glm::vec3 ink(.92F,.96F,1),muted(.57F,.68F,.77F),cyan(.38F,.82F,.93F),amber(1,.75F,.25F);
        ui.rounded(-.054F,-.43F,.658F,.446F,.010F,detailed?glm::vec3(.055F,.092F,.13F):glm::vec3(.07F,.115F,.15F),.007F);
        ui.text("SOURCE / "+std::to_string(t.available)+(live?" FRAMES":" SAMPLE FRAMES"),-.039F,.003F,.0028F,muted,.010F);
        ui.text(t.valid()?std::to_string(t.count())+" FRAMES TO LOAD":"START MUST BE <= END",-.039F,-.092F,.0028F,t.valid()?cyan:amber,.012F);
        wheels.draw(ui,t);
        const bool ready=t.phase==2;
        const auto b=scrubber(detailed);const float y=b.y+b.w*.5F;
        const float f=t.hasFrame() && t.loadedCount()>1?float(t.index)/(t.loadedCount()-1):0;
        const bool hot=hover==311 || drag==311;const auto colour=ready?(hot?amber:cyan):glm::vec3(.30F,.36F,.42F);
        if(detailed){
            ui.bevel(b.x-.013F,y-.020F,b.z+.026F,.040F,.01F,.008F,.022F,.005F,{.19F,.26F,.33F});
            ui.rounded(b.x,y-.006F,b.z,.012F,.005F,{.018F,.028F,.038F},.024F);
            for(int i=0;i<=20;++i)ui.rect(b.x+b.z*i/20,y-.058F,.002F,i%5==0?.021F:.010F,muted,.025F);
            ui.bevel(b.x+b.z*f-.022F,y-.027F,.044F,.058F,.008F,.024F,hot?.048F:.040F,.005F,colour);
            for(int i=-1;i<=1;++i)ui.rect(b.x+b.z*f+i*.009F-.001F,y-.015F,.002F,.030F,{.06F,.11F,.14F},.050F);
            ui.text(std::to_string(t.hasFrame()?t.loadedFirst:t.first),b.x,y-.068F,.0023F,muted,.027F);
            ui.text(std::to_string(t.hasFrame()?t.finalFrame():t.last),b.x+b.z-.08F,y-.068F,.0023F,muted,.027F);
        }else{
            ui.rounded(b.x,y-.004F,b.z,.008F,.003F,{.22F,.30F,.36F},.013F);
            if(ready)ui.rect(b.x,y-.004F,b.z*f,.008F,colour,.015F);
            ui.rounded(b.x+b.z*f-.013F,y-.017F,.026F,.034F,.005F,colour,.020F);
            ui.text(ready?"SAMPLE "+std::to_string(t.index+1)+" / "+std::to_string(t.loadedCount()):"PLAYBACK LOCKED UNTIL LOAD",b.x,-.338F,.0028F,muted,.023F);
        }
        if(hot && ready){
            const float x=std::clamp(b.x+b.z*f-.07F,b.x,b.x+b.z-.14F);
            ui.rounded(x,y+.027F,.14F,.034F,.006F,{.1F,.19F,.24F},.053F);
            ui.text(std::to_string(t.sourceFrame()),x+.008F,y+.051F,.0032F,amber,.055F);
        }
        if(live)return;
        const std::string status=t.phase==1?(t.progress<.5F?"DOWNLOAD ":"PREPARE ")+std::to_string(int(t.progress*100))+"%":ready?"READY / "+std::to_string(t.loadedCount())+" LOADED":"SET RANGE + INTERVAL, THEN LOAD";
        ui.text(status,-.60F,-.477F,.0028F,t.phase==1?amber:cyan,.012F);
        ui.rect(-.60F,-.508F,1.20F,.010F,{.18F,.25F,.30F},.012F);
        if(t.phase)ui.rect(-.60F,-.508F,1.20F*(ready?1.F:t.progress),.010F,cyan,.014F);
        ui.text("SAMPLE LOADER / NO LIVE DOWNLOAD",-.60F,-.449F,.0024F,muted,.012F);
    }
    template<class UI> void drawPopup(UI& ui,const TrajectoryState& t) const {
        if(!popup)return;
        const glm::vec3 ink(.93F,.96F,1),muted(.61F,.72F,.82F),cyan(.4F,.83F,.94F),amber(1,.75F,.3F);
        ui.rounded(-.061F,-.441F,.674F,.547F,.016F,{.075F,.115F,.16F},.06F);
        if(popup==1){
            ui.text(field==300?"START FRAME":field==301?"END FRAME":field==302?"FRAME INTERVAL":"GO TO SOURCE FRAME",-.035F,.080F,.0038F,cyan,.063F);
            ui.text(digits.empty()?"_":digits,-.035F,.023F,.006F,ink,.063F);
            ui.text(numberValid(t)?(field==306?"SNAPS TO NEAREST LOADED FRAME":"ENTER AN EXACT INTEGER"):"ENTER A VALUE IN THE RANGE BELOW",-.035F,-.027F,.0025F,numberValid(t)?muted:amber,.063F);
            ui.text("RANGE "+std::to_string(field==306?t.loadedFirst:1)+" - "+std::to_string(field==306?t.finalFrame():t.available),-.035F,-.322F,.0028F,muted,.063F);
            ui.text("TYPE DIGITS / ENTER APPLY / ESC CANCEL",-.035F,-.348F,.0024F,muted,.063F);
        }else{
            ui.text("LARGE TRAJECTORY",-.035F,.074F,.004F,amber,.063F);
            ui.text(std::to_string(t.count())+" FRAMES",-.035F,.014F,.005F,ink,.063F);
            ui.text("RANGE "+std::to_string(t.first)+" - "+std::to_string(t.last),-.035F,-.043F,.0032F,muted,.063F);
            ui.text("EVERY "+std::to_string(t.interval)+" / CONFIRM AT 500+",-.035F,-.084F,.003F,muted,.063F);
            ui.text("MORE FRAMES USE MORE MEMORY",-.035F,-.122F,.003F,ink,.063F);
            ui.text("AND TAKE LONGER TO PREPARE.",-.035F,-.147F,.003F,ink,.063F);
        }
    }
};
}
