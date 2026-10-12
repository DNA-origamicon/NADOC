#pragma once
#include "controller_prompt.hpp"
#include <iomanip>

namespace simulation_study {
struct ScaleState {float low=0,high=1;int palette=0;};
// Six desktop palettes, including each scalar mode's established default.
// Exact anchors from frontend/src/ui/colormaps.js; interpolate as that module does.
inline constexpr std::array<const char*,6> paletteNames{"VIRIDIS","MAGMA","TURBO","JET","GREEN-RED","COOL-WARM"};
inline const std::array<std::vector<glm::vec3>,6> paletteStops{{
    {{68,1,84},{59,82,139},{33,144,140},{93,201,99},{253,231,37}},
    {{0,0,4},{81,18,124},{183,55,121},{252,137,97},{252,253,191}},
    {{48,18,59},{50,102,229},{26,199,194},{132,228,72},{236,203,40},{241,96,26},{122,4,3}},
    {{0,0,255},{0,255,255},{0,255,0},{255,255,0},{255,0,0}},
    {{63,185,80},{210,153,34},{248,81,73}},
    {{59,76,192},{144,178,254},{221,221,221},{246,158,131},{180,4,38}}
}};
inline glm::vec3 paletteColour(int palette,float t) {
    const auto& stops=paletteStops[palette];const float p=std::clamp(t,0.F,1.F)*(stops.size()-1);
    const auto i=std::min(size_t(p),stops.size()-2);return glm::mix(stops[i],stops[i+1],p-i)/255.F;
}
inline bool scalarMode(int m){return m==2 || m==3 || m==4 || m==6 || m==10;}
inline void scaleBound(ScaleState& s,int handle,float fraction) {
    const float f=std::clamp(fraction,0.F,1.F);
    if(handle==200)s.low=std::min(f,s.high-.02F);
    else s.high=std::max(f,s.low+.02F);
}
class ColourScaleGallery {
 public:
    nadoc_vr::PaletteControllerPrompt prompt;
    int pulses=0,handleHover=-1,drag=-1;float flash=0;double clock=0;
    bool pad=false,mouseGesture=false;
    static constexpr glm::vec2 wheelCenter{.275F,-.202F};
    void close(){prompt.withdraw("simulation-palette");drag=-1;pad=false;mouseGesture=false;}
    void open(ScaleState& s){
        close();pulses=0;
        nadoc_vr::PaletteControllerPrompt::Request r{"COLOUR MAP","",{},[&s](const auto& id){s.palette=std::stoi(id);},"simulation-palette"};
        for(int i=0;i<6;++i)r.options.push_back({std::to_string(i),paletteNames[i]});
        prompt.show(std::move(r));
    }
    void tick(float dt,bool pressed,glm::vec2 pointer,bool valid) {
        clock+=dt;flash=std::max(0.F,flash-dt);
        nadoc_vr::HandPose hand{valid,false,{0,0,0},{1,0,0,0}};
        // Desktop pointer direction substitutes for the left touchpad axis only.
        // Fresh press, dead zone, three timed pulses and release commit are shared.
        prompt.update(pressed,(pointer-wheelCenter)/.19F,hand,clock,[&](float){++pulses;flash=.10F;});
    }
    static std::string value(float f,int mode){
        const float lo=mode==6?-1.F:0.F,hi=(mode==10 || mode==6)?1.F:mode==3?5.F:2.F;
        std::ostringstream o;o<<std::fixed<<std::setprecision(2)<<(lo+(hi-lo)*f);return o.str();
    }
    static glm::vec4 bar(bool horizontal,const ScaleState& s,int id){
        const float f=id==200?s.low:s.high;
        return horizontal?glm::vec4(-.005F+.535F*f-.016F,-.082F,.032F,.059F):glm::vec4(.435F,-.310F+.220F*f-.014F,.134F,.028F);
    }
    static float fraction(bool horizontal,glm::vec2 p){return horizontal?(p.x+.005F)/.535F:(p.y+.310F)/.220F;}
    template<class UI> static void ramp(UI& ui,int map,float x,float y,float w,float h,bool horizontal,float z){
        for(int i=0;i<80;++i){const float t=i/80.F;
            ui.rect(x+(horizontal?w*t:0),y+(horizontal?0:h*t),horizontal?w/80+.0001F:w,horizontal?h:h/80+.0001F,paletteColour(map,t),z);}
    }
    template<class UI> void draw(UI& ui,bool horizontal,const ScaleState& s,int mode) const {
        const glm::vec3 ink(.92F,.96F,1),muted(.57F,.68F,.78F),accent(.4F,.83F,.94F);
        const std::string title=mode==2?"RMSF (NM)":mode==3?"DEVIATION (NM)":mode==6?"STRAIN":mode==10?"PROPENSITY":"RMSF (NM)";
        if(horizontal){
            ui.rounded(-.05F,-.206F,.65F,.219F,.012F,{.055F,.10F,.145F},.009F);
            ui.text(title,-.033F,-.007F,.003F,accent,.013F);
            ramp(ui,s.palette,-.005F,-.066F,.535F,.033F,true,.014F);
            ui.text("MIN "+value(s.low,mode),-.034F,-.110F,.0028F,ink,.015F);
            ui.text("MAX "+value(s.high,mode),.308F,-.110F,.0028F,ink,.015F);
        }else{
            ui.rounded(.414F,-.424F,.186F,.437F,.009F,{.12F,.17F,.21F},.009F);
            ui.text(title,.425F,-.004F,.00215F,accent,.013F);
            ui.text("MAX "+value(s.high,mode),.427F,-.049F,.00225F,ink,.013F);
            ramp(ui,s.palette,.48F,-.310F,.045F,.220F,false,.014F);
            ui.text("MIN "+value(s.low,mode),.427F,-.345F,.00225F,ink,.013F);
        }
        for(int id:{200,201}){
            auto b=bar(horizontal,s,id);const bool hot=handleHover==id || drag==id;
            const auto colour=hot?glm::vec3(1,.77F,.22F):ink;
            ui.rounded(b.x-(hot?.003F:0),b.y-(hot?.003F:0),b.z+(hot?.006F:0),b.w+(hot?.006F:0),.004F,hot?glm::vec3(.50F,.32F,.08F):glm::vec3(.045F,.065F,.09F),.016F);
            if(horizontal)ui.rect(b.x+b.z*.36F,b.y+.004F,b.z*.28F,b.w-.008F,colour,.018F);
            else ui.rect(b.x+.003F,b.y+b.w*.32F,b.z-.006F,b.w*.36F,colour,.018F);
        }
        if(handleHover>=0 || drag>=0)ui.text((drag>=0?"DRAG ":"DRAG TO SET ")+std::string((drag>=0?drag:handleHover)==200?"MIN":"MAX"),-.046F,-.453F,.0027F,{1,.77F,.22F},.02F);
    }
    template<class UI> void drawPicker(UI& ui,int selected,bool horizontal) const {
        if(!prompt.active())return;
        const glm::vec3 ink(.94F,.97F,1);
        ui.rounded(-.061F,-.442F,.674F,.546F,.016F,horizontal?glm::vec3(.07F,.12F,.18F):glm::vec3(.13F,.17F,.21F),.04F);
        ui.text("COLOUR MAP / LEFT PAD",-.037F,.080F,.0032F,ink,.05F);
        for(int i=0;i<3;++i)ui.rounded(.42F+i*.042F,.057F,.025F,.025F,.01F,i<pulses?(flash>0?glm::vec3(1,.8F,.2F):glm::vec3(.4F,.85F,.7F)):glm::vec3(.25F),.05F);
        ui.text("HOLD SPACE OR MOUSE / SLIDE / RELEASE",-.037F,.032F,.0026F,{.64F,.76F,.86F},.05F);
        for(int i=0;i<6;++i){
            const auto d=nadoc_vr::PaletteControllerPrompt::direction(i,6);
            const float a=std::atan2(d.x,d.y),half=glm::pi<float>()/6-.035F;
            const auto p=[&](float angle,float r){return glm::vec3(wheelCenter+glm::vec2(std::sin(angle),std::cos(angle))*r,.045F);};
            const bool hot=prompt.hovered()==size_t(i);
            for(int j=0;j<30;++j){const float aa=a-half+2*half*j/30,bb=a-half+2*half*(j+1)/30;
                auto colour=hot?glm::vec3(.53F,.36F,.09F):selected==i?glm::vec3(.1F,.32F,.36F):glm::vec3(.08F,.115F,.15F);
                ui.triangle(p(aa,.055F),p(aa,.214F),p(bb,.214F),colour);ui.triangle(p(aa,.055F),p(bb,.214F),p(bb,.055F),colour);
                ui.triangle(p(aa,.196F),p(aa,.209F),p(bb,.209F),paletteColour(i,j/29.F));
                ui.triangle(p(aa,.196F),p(bb,.209F),p(bb,.196F),paletteColour(i,j/29.F));}
            const glm::vec2 label=wheelCenter+d*.14F;
            const std::string name=paletteNames[i];const float scale=.0022F;
            ui.text(name,label.x-name.size()*3*scale,label.y+.006F,scale,hot?glm::vec3(1,.83F,.3F):ink,.05F);
            ramp(ui,i,label.x-.052F,label.y-.022F,.104F,.012F,true,.05F);
        }
        ui.text("ESC CANCEL / CENTER RELEASE KEEPS CURRENT",-.037F,-.425F,.0024F,{.64F,.76F,.86F},.05F);
    }
};
}
