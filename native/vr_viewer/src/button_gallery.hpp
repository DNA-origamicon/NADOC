#pragma once
#include "solid_ui.hpp"

// Geometry studies inspired by the named systems; no copied assets or platform
// input emulation. Every sample uses the same release-to-toggle interaction.
class ButtonGallery {
 public:
    struct Button {bool hovered=false,selected=false;int hand=-1,clicks=0;float press=0;};
    std::array<Button,6> buttons{};
    bool disabled=false,demo=false;
    float clock=0;
    static constexpr std::array<const char*,6> names{"RAISED SLATE","SOFT CAPSULE","FILLED PILL","OUTLINE","OPERATOR","ROUND PUSH"};
    static constexpr std::array<const char*,6> sources{"MRTK / HOLOLENS","VISIONOS INSPIRED","MATERIAL 3","MATERIAL 3","BLENDER INSPIRED","MRTK CIRCULAR"};
    static glm::vec3 center(size_t i) {return {-.51F+float(i%3)*.51F,.255F-float(i/3)*.43F,.035F};}
    static float height(size_t i){return i==5?.16F:.12F;}
    static float width(size_t i){return i==5?.16F:.35F;}
    static float radius(size_t i){return i==0?.014F:i==4?.007F:height(i)*.5F;}
    static bool contains(size_t i,glm::vec3 p) {
        const auto c=center(i);const float hx=width(i)*.5F,hy=height(i)*.5F,r=radius(i);
        const glm::vec2 q=glm::max(glm::abs(glm::vec2(p-c))-glm::vec2(hx-r,hy-r),glm::vec2(0));
        return std::abs(p.x-c.x)<=hx && std::abs(p.y-c.y)<=hy && glm::dot(q,q)<=r*r+1e-8F;
    }
    void reset(){buttons={};disabled=false;demo=false;clock=0;}
    void toggleDemo(){const bool next=!demo;reset();demo=next;}
    int demoState() const {return int(clock/1.3F)%5;}
    const char* state(size_t i) const {
        if(disabled || (demo && demoState()==4))return "DISABLED";
        if(buttons[i].hand>=0 || (demo && demoState()==2))return "PRESSED";
        if(buttons[i].selected || (demo && demoState()==3))return "SELECTED";
        if(buttons[i].hovered || (demo && demoState()==1))return "HOVER";
        return "IDLE";
    }
    void update(const nadoc_vr::MenuPlacement& placement,const std::array<nadoc_vr::HandPose,2>& hands,
            const std::array<bool,2>& clicked,const std::array<bool,2>& held,float dt,
            std::array<std::optional<glm::vec3>,2>& beam) {
        clock+=dt;
        for(auto& b:buttons)b.hovered=false;
        for(size_t hand=0;hand<2;++hand) {
            // Sample the raised front face, not the panel behind it.
            auto p=placement.rayPanelLocalPoint(hands[hand],{-10,-10},{10,10});
            std::optional<size_t> hit;
            if(p)for(size_t i=0;i<buttons.size();++i) {
                const auto origin=placement.localPoint(hands[hand].position);
                const auto d=placement.localPoint(hands[hand].position+hands[hand].orientation*glm::vec3(0,0,-1))-origin;
                if(std::abs(d.z)<1e-7F)continue;
                const float t=(frontDepth(i)-origin.z)/d.z;
                const auto contact=origin+t*d;
                if(t>0 && contains(i,contact)){hit=i;beam[hand]=placement.worldPoint(contact);buttons[i].hovered=true;break;}
            }
            for(size_t i=0;i<buttons.size();++i)if(buttons[i].hand==int(hand)) {
                if(!hands[hand].valid || disabled){buttons[i].hand=-1;continue;}
                if(!held[hand]) {
                    if(hit==i){buttons[i].selected=!buttons[i].selected;++buttons[i].clicks;}
                    buttons[i].hand=-1;
                }
            }
            if(hit && clicked[hand] && !disabled && buttons[*hit].hand<0) {
                demo=false;
                // Do not transfer a held trigger to an adjacent button.
                bool owns=false;for(const auto& b:buttons)owns|=b.hand==int(hand);
                if(!owns)buttons[*hit].hand=int(hand);
            }
        }
        for(size_t i=0;i<buttons.size();++i) {
            const bool down=!disabled && (buttons[i].hand>=0 || (demo && demoState()==2));
            buttons[i].press+=(float(down)-buttons[i].press)*(1-std::exp(-dt*28));
        }
    }
    float frontDepth(size_t i) const {
        const float depth=i==0?.035F:i==1?.020F:i==2?.017F:i==3?.012F:i==4?.019F:.043F;
        return depth-buttons[i].press*(i==3?.002F:.009F);
    }
    void render(SolidUi& ui) const {
        const glm::vec3 text(.89F,.93F,.98F),muted(.53F,.64F,.75F),blue(.38F,.72F,1.F);
        ui.text("BUTTONS / COMPONENT GALLERY",-.73F,.595F,.0062F,text);
        ui.text("POINT, PRESS, RELEASE. SAME ACTION / SIX SURFACES.",-.73F,.52F,.0038F,muted);
        for(size_t i=0;i<buttons.size();++i) {
            const auto c=center(i);const std::string st=state(i);
            const bool off=st=="DISABLED",focus=st=="HOVER"||st=="PRESSED",on=st=="SELECTED";
            ui.rounded(c.x-.235F,c.y-.185F,.47F,.385F,.018F,{.052F,.071F,.096F},.002F);
            ui.text(std::to_string(i+1)+" / "+names[i],c.x-.212F,c.y+.17F,.0042F,text);
            ui.text(sources[i],c.x-.212F,c.y+.115F,.0031F,muted);
            const float w=width(i),h=height(i),r=radius(i),z=frontDepth(i);
            const float x=c.x-w*.5F,y=c.y-h*.5F;
            const glm::vec3 neutral(.25F,.31F,.39F),disabledColor(.12F,.15F,.19F);
            glm::vec3 face=i==1?glm::vec3(.76F,.82F,.88F):i==2?glm::vec3(.35F,.23F,.63F):neutral;
            if(on)face={.12F,.49F,.37F};
            if(focus)face=glm::min(face+glm::vec3(.10F),glm::vec3(1));
            if(off)face=disabledColor;
            const auto border=off?glm::vec3(.22F,.26F,.31F):on?glm::vec3(.35F,.90F,.65F):focus?glm::vec3(1,.74F,.30F):blue;
            ui.rounded(x+.006F,y-.008F,w+.009F,h+.012F,r,{.018F,.026F,.039F},.003F);
            if(i==0) {
                ui.raisedSlate(x,y,w,h,z,face,border);
            } else if(i==3) {
                ui.rounded(x,y,w,h,r,border,z);
                ui.rounded(x+.003F,y+.003F,w-.006F,h-.006F,r-.003F,on?face:glm::vec3(.052F,.071F,.096F),z+.001F);
            } else {
                // A solid rim plus sloped sidewalls gives the raised face an
                // actual travel distance in stereo and when orbiting on desktop.
                ui.rounded(x-.004F,y-.004F,w+.008F,h+.008F,r+.004F,border*.6F,.004F);
                ui.bevel(x,y,w,h,r,.005F,z,i==0?.010F:i==4?.003F:.006F,face);
            }
            const auto ink=off?muted:i==1 && !on?glm::vec3(.07F,.12F,.18F):text;
            const float scale=i==5?.0034F:.0045F;
            ui.text("SELECT",c.x-18*scale,c.y+3*scale,scale,ink,z+.002F);
            ui.text(st+(on?" / ON":""),c.x-.212F,c.y-.112F,.0035F,off?muted:on?glm::vec3(.35F,.9F,.65F):blue);
            ui.text("CLICKS "+std::to_string(buttons[i].clicks),c.x-.212F,c.y-.153F,.003F,muted);
        }
    }
    std::string observation(const nadoc_vr::MenuPlacement& p) const {
        std::ostringstream out;out<<'[';
        for(size_t i=0;i<buttons.size();++i) {
            if(i)out<<',';
            const auto& b=buttons[i];auto local=center(i);local.z=frontDepth(i);const auto world=p.worldPoint(local);
            out<<"{\"style\":\""<<names[i]<<"\",\"state\":\""<<state(i)<<"\",\"hovered\":"<<(b.hovered?"true":"false")
               <<",\"selected\":"<<(b.selected?"true":"false")<<",\"clicks\":"<<b.clicks
               <<",\"position\":["<<world.x<<','<<world.y<<','<<world.z<<"]}";
        }
        out<<']';return out.str();
    }
};
