#pragma once
#include "button_gallery.hpp"
#include "card_gallery.hpp"

class ComponentGallery {
 public:
    bool active=false, posed=false, demo=false, desktop=false;
    bool buttonMode=false, cardMode=false;
    CardGallery cardStyles;
    ButtonGallery buttonStyles;
    nadoc_vr::MenuPlacement placement;
    struct Wheel {
        nadoc_vr::ThumbwheelControl control;
        int maximum=10,value=5;
        int hand=-1;
        bool hovered=false;
    };
    std::array<Wheel,9> wheels;
    std::array<std::optional<glm::vec3>,2> beam{};
    std::array<bool,4> buttonHover{};
    float demoTime=0;
    int demoWheel=-1;
    SolidUi ui;
    ComponentGallery() {reset();}
    static constexpr std::array<float,3> exposures{.20F,.35F,.50F};
    static glm::vec3 center(size_t i) {return {-.64F+float(i%3)*.51F,.26F-float(i/3)*.285F,.012F};}
    static nadoc_vr::ThumbwheelShape shape(size_t i) {
        const int maximum=i/3==0?10:i/3==1?100:1000;
        return nadoc_vr::thumbwheelPreset(maximum,exposures[i%3]);
    }
    void reset() {
        buttonStyles.reset();cardStyles.reset();
        for(size_t i=0;i<wheels.size();++i) {
            wheels[i]={};wheels[i].maximum=i/3==0?10:i/3==1?100:1000;
            wheels[i].value=wheels[i].maximum/2;
        }
        demoTime=0;demoWheel=-1;
    }
    void toggleDemo() {
        if(cardMode){cardStyles.toggleDemo();demo=cardStyles.demo;return;}
        if(buttonMode){buttonStyles.toggleDemo();demo=buttonStyles.demo;return;}
        if(demo){demo=false;if(demoWheel>=0)wheels[demoWheel].control.release();demoWheel=-1;}
        else {reset();demo=true;}
    }
    void show(glm::vec3 head,glm::quat orientation) {
        placement.openDocked(head+orientation*glm::vec3(0,-.06F,-1.30F),orientation);posed=true;
    }
    static bool inside(glm::vec3 p,float x,float y,float w,float h) {
        return p.x>=x && p.x<=x+w && p.y>=y && p.y<=y+h;
    }
    std::optional<glm::vec3> wheelHit(size_t i,const nadoc_vr::HandPose& hand) const {
        return nadoc_vr::thumbwheelHit(shape(i),center(i),placement,hand);
    }

    void step(size_t i,int amount) {
        auto& wheel=wheels[i];const int next=std::clamp(wheel.value+amount,0,wheel.maximum);
        const bool limit=amount && (next==0 || next==wheel.maximum);
        wheel.value=next;
        // Stop at a range endpoint rather than visibly spinning a frozen value.
        if(limit){wheel.control.reset();wheel.hand=-1;}
    }
    void update(const std::array<nadoc_vr::HandPose,2>& hands,
            const std::array<bool,2>& clicked,const std::array<bool,2>& pressed,
            float dt,glm::vec3 head,glm::quat orientation) {
        if(!active)return;
        if(!posed)show(head,orientation);
        dt=std::clamp(dt,0.F,.05F);beam.fill(std::nullopt);buttonHover.fill(false);
        if(cardMode){cardStyles.update(placement,hands,clicked,pressed,dt,beam);demo=cardStyles.demo;footerInput(hands,clicked,head,orientation);return;}
        if(buttonMode) {
            buttonStyles.update(placement,hands,clicked,pressed,dt,beam);demo=buttonStyles.demo;
            footerInput(hands,clicked,head,orientation);return;
        }
        for(auto& wheel:wheels)wheel.hovered=false;
        for(size_t h=0;h<2;++h) {
            const auto p=placement.rayPanelLocalPoint(hands[h],{-10,-10},{10,10});
            for(size_t i=0;i<wheels.size();++i)if(wheels[i].hand==int(h)) {
                if(!pressed[h] || !p || !hands[h].valid){wheels[i].control.release();wheels[i].hand=-1;}
                else {step(i,wheels[i].control.drag(p->y,dt));beam[h]=placement.worldPoint(*p);}
            }
            if(!p)continue;
            for(size_t i=0;i<wheels.size();++i) {
                const auto hit=wheelHit(i,hands[h]);
                if(!hit)continue;
                wheels[i].hovered=true;beam[h]=placement.worldPoint(*hit);
                if(clicked[h] && wheels[i].hand<0) {
                    if(demoWheel>=0)wheels[demoWheel].control.release();
                    demo=false;demoWheel=-1;
                    // A hand has exactly one wheel owner even when its ray crosses another.
                    for(auto& wheel:wheels)if(wheel.hand==int(h)){wheel.control.release();wheel.hand=-1;}
                    wheels[i].hand=int(h);wheels[i].control.begin(p->y);
                }
            }

        }
        footerInput(hands,clicked,head,orientation);
        if(demo) {
            const int index=int(demoTime/2.8F)%9;
            const float t=std::fmod(demoTime,2.8F);
            if(index!=demoWheel){demoWheel=index;wheels[index].control.begin(0);}
            if(t<.5F)step(index,wheels[index].control.drag(t*.40F,dt));
            else if(wheels[index].control.dragging())wheels[index].control.release();
            demoTime+=dt;
        }
        for(size_t i=0;i<wheels.size();++i)step(i,wheels[i].control.updateMomentum(dt));
    }
    int footerCount() const {return (buttonMode||cardMode)?4:3;}
    float footerX(int i) const {return -.73F+i*((buttonMode||cardMode)?.37F:.49F);}
    float footerWidth() const {return (buttonMode||cardMode)?.34F:.44F;}
    void footerInput(const std::array<nadoc_vr::HandPose,2>& hands,const std::array<bool,2>& clicked,
            glm::vec3 head,glm::quat orientation) {
        for(size_t hand=0;hand<2;++hand) {
            const auto p=placement.rayPanelLocalPoint(hands[hand],{-1,-1},{1,1});if(!p)continue;
            for(int button=0;button<footerCount();++button)if(inside(*p,footerX(button),-.61F,footerWidth(),.07F)) {
                beam[hand]=placement.worldPoint(*p);buttonHover[button]=true;
                if(clicked[hand]) {
                    if(button==0)toggleDemo();
                    if(button==1){reset();demo=false;}
                    if(button==2)show(head,orientation);
                    if(button==3 && cardMode){cardStyles.disabled=!cardStyles.disabled;cardStyles.demo=demo=false;}
                    if(button==3 && !cardMode){buttonStyles.disabled=!buttonStyles.disabled;buttonStyles.demo=demo=false;}
                }
            }
        }
    }
    void render(const glm::mat4& vp) {
        if(!active || !posed)return;
        ui.vertices.clear();
        const glm::vec3 text(.89F,.93F,.98F),muted(.53F,.64F,.75F),accent(.42F,.77F,1.F);
        ui.rect(-.79F,-.67F,1.58F,1.32F,{.035F,.048F,.067F},0);
        if(cardMode)cardStyles.render(ui);
        else if(buttonMode)buttonStyles.render(ui);
        else {
        ui.text("THUMBWHEEL / COMPONENT GALLERY",-.73F,.595F,.0062F,text);
        ui.text("GRAB + DRAG UP/DOWN. RELEASE TO COAST.",-.73F,.52F,.0038F,muted);
        for(size_t col=0;col<3;++col) {
            const float x=-.73F+col*.51F;
            ui.text(col==0?"SHALLOW / 20%":col==1?"INSET / 35%":"HALF / 50%",x,.445F,.0043F,accent);
        }
        for(size_t i=0;i<wheels.size();++i) {
            const auto c=center(i);const auto s=shape(i);const auto& w=wheels[i];
            const bool focus=w.hovered || w.control.dragging() || (demo && demoWheel==int(i));
            ui.rect(c.x-.067F,c.y-s.halfOpening()-.018F,.134F,2*s.halfOpening()+.036F,{.10F,.14F,.19F},.002F);
            ui.rect(c.x-.05F,c.y-s.halfOpening()-.004F,.10F,2*s.halfOpening()+.008F,{.012F,.018F,.026F},.006F);
            ui.wheel(s,w.control.phase(),c,focus?glm::vec3(1,.72F,.26F):glm::vec3(.57F,.74F,.88F),[](auto p){return p;});
            ui.text("0 - "+std::to_string(w.maximum),c.x+.085F,c.y+.062F,.004F,muted);
            ui.rect(c.x+.08F,c.y-.019F,.235F,.06F,{.065F,.087F,.12F});
            ui.text(std::to_string(w.value),c.x+.10F,c.y+.021F,.006F,text);
            ui.text("D "+std::to_string(int(std::round(s.radius*2000*placement.scale())))+" MM",c.x+.085F,c.y-.042F,.0033F,muted);
            const std::string state=w.control.dragging()?"DRAGGING":w.control.moving()?"COASTING":"READY";
            ui.text(state,c.x+.085F,c.y-.078F,.0031F,focus?accent:muted);
        }
        }
        for(int button=0;button<footerCount();++button) {
            const float x=footerX(button);
            ui.rect(x,-.61F,footerWidth(),.07F,buttonHover[button]?glm::vec3(.20F,.31F,.42F):glm::vec3(.10F,.18F,.25F));
            ui.text(button==0?(demo?"STOP DEMO":"PLAY DEMO"):button==1?"RESET":button==2?"RECENTER":(cardMode?cardStyles.disabled:buttonStyles.disabled)?"ENABLE":"DISABLE",x+.035F,-.565F,.004F,text);
        }
        if(desktop)ui.text("F FRONT / O ANGLED / RIGHT DRAG ORBIT / SCROLL ZOOM / S CAPTURE",-.73F,-.635F,.003F,muted);
        const auto model=glm::translate(glm::mat4(1),placement.position())*glm::mat4_cast(placement.orientation())*glm::scale(glm::mat4(1),glm::vec3(placement.scale()));
        ui.render(vp*model);
    }
    template<class Line> void guides(const std::array<nadoc_vr::HandPose,2>& hands,Line line) {
        if(active)for(size_t h=0;h<2;++h)if(beam[h])line(hands[h].position,*beam[h],glm::vec3(.4F,.9F,1));
    }
    std::string observation() const {
        std::ostringstream out;out<<"{\"component\":\""<<(cardMode?"cards":buttonMode?"buttons":"thumbwheel")<<"\",\"samples\":"<<(cardMode?cardStyles.observation(placement):buttonStyles.observation(placement))<<",\"active\":"<<(active?"true":"false")<<",\"demo\":"<<(demo?"true":"false")<<",\"orientation_xyzw\":["<<placement.orientation().x<<','<<placement.orientation().y<<','<<placement.orientation().z<<','<<placement.orientation().w<<"],\"wheels\":[";
        for(size_t i=0;i<wheels.size();++i) {
            if(i)out<<',';
            const auto& w=wheels[i];const auto c=placement.worldPoint(center(i));
            const auto s=shape(i);
            const auto surface=placement.worldPoint(center(i)+glm::vec3(0,0,s.radius+s.centerDepth()));
            out<<"{\"surface_position\":["<<surface.x<<','<<surface.y<<','<<surface.z<<"],\"value\":"<<w.value<<",\"maximum\":"<<w.maximum<<",\"hovered\":"<<(w.hovered?"true":"false")
               <<",\"dragging\":"<<(w.control.dragging()?"true":"false")<<",\"moving\":"<<(w.control.moving()?"true":"false")
               <<",\"position\":["<<c.x<<','<<c.y<<','<<c.z<<"]}";
        }
        out<<"],\"buttons\":[";
        for(size_t i=0;i<size_t(footerCount());++i) {
            if(i)out<<',';
            const auto p=placement.worldPoint({footerX(int(i))+footerWidth()*.5F,-.575F,.008F});
            out<<"{\"hovered\":"<<(buttonHover[i]?"true":"false")<<",\"position\":["<<p.x<<','<<p.y<<','<<p.z<<"]}";
        }
        out<<"]}";return out.str();
    }
};
