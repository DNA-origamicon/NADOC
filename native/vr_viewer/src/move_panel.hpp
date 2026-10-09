#pragma once
#include "sidebar_menu.hpp"
#include <glm/gtx/quaternion.hpp>
#include <iomanip>
#include <sstream>
namespace nadoc_vr {
class MovePanel {
 public:
    static constexpr size_t selectHand=0, moveHand=1;
    bool active=false, selecting=false, snap=false, rotating=false;
    bool selectionEnabled(size_t h) const { return !active || (!hand && !wheelHand && (selecting || h==selectHand)); }
    size_t savedOffset=0, wheelIndex=0;
    std::optional<size_t> hand, wheelHand;
    std::array<bool,2> nearby{};
    std::array<ThumbwheelControl,6> wheels;
    glm::mat4 startHand{1},startModel{1};
    glm::mat3 axes{1};
    float nmScale=1, rayDistance=0;
    glm::vec3 pivot{},grabPoint{},positionNm{},rotationDegrees{},startPosition{},startRotation{};
    std::optional<glm::vec3> beamEnd;
    bool moving() const {return hand || wheelHand || std::any_of(wheels.begin(),wheels.end(),[](const auto& w){return w.moving();});}
    void reset() {
        hand.reset();wheelHand.reset();for(auto& w:wheels)w.reset();
        positionNm=rotationDegrees=glm::vec3(0);nearby.fill(false);beamEnd.reset();
    }
    void enter(std::array<SidebarMenu,2>& menus) {
        if(!active){savedOffset=menus[1].offset();reset();}
        active=true;menus[1].open=true;menus[1].offsets[menus[1].selected]=0;
        menus[1].focus.reset();
    }
    void exit(std::array<SidebarMenu,2>& menus) {
        active=false;reset();
        auto& m=menus[1];m.customTab.reset();m.offsets[m.selected]=savedOffset;m.focus.reset();
    }
    static std::string number(float value,int decimals) {
        std::ostringstream out;out<<std::fixed<<std::setprecision(decimals)<<(std::abs(value)<.0005F?0.F:value);return out.str();
    }
    void refresh(std::array<SidebarMenu,2>& menus,const std::string& kind,const std::string& status) const {
        if(!active)return;
        SidebarTab tab{1,"move","Move / Rotate",{}};
        auto row=[&](std::string id,std::string label,std::string detail="") {
            tab.rows.push_back({"move:"+id,label,detail,"move:"+id,{}});
        };
        row("back","RETURN TO TOOLS",status);
        row("apply","APPLY");row("cancel","CANCEL");
        row("selection",selecting || kind=="none"?"Selection: point and click":"Selection: "+kind,
            "LEFT PAD: FILTER / CLICK TO CHANGE");
        row("snap",snap?"15 DEG SNAP: ON":"15 DEG SNAP: OFF","TRIGGER: MOVE / GRIP: ROTATE");
        for(size_t i=0;i<6;++i) {
            const auto id=std::to_string(i);
            row(id+"-wheel","");
            row(id+":value",std::string(i<3?"":"R")+"XYZ"[i%3]+" "+number(i<3?positionNm[i]:rotationDegrees[i-3],i<3?3:1)+(i<3?" nm":" deg"));
            row(id+":less","-1");row(id+":more","+1");
        }
        row("undo","UNDO");row("redo","REDO");row("recenter","Frame model");
        menus[1].customTab=std::move(tab);
    }
    void configure(glm::vec3 localPivot,glm::mat3 sourceAxes,float scale) {
        pivot=localPivot;axes=sourceAxes;nmScale=scale;
    }
    glm::mat4 transform() const {
        const auto rotation=axes*glm::mat3_cast(glm::quat(glm::radians(rotationDegrees)))*glm::transpose(axes);
        return glm::translate(glm::mat4(1),pivot+axes*positionNm*nmScale)*glm::mat4(rotation)*glm::translate(glm::mat4(1),-pivot);
    }
    void adjust(size_t index,int steps) {
        if(index<3)positionNm[index]=std::round((positionNm[index]+steps)*1000.F)/1000.F;
        else rotationDegrees[index-3]+=steps; // Manual detents are always one degree.
    }
    void begin(size_t h,const HandPose& pose,const glm::mat4& model,const glm::vec3& center,bool rotate=false) {
        if(h!=moveHand)return;
        hand=h;rotating=rotate;startHand=poseMatrix(pose);startModel=model;
        pivot=glm::vec3(glm::inverse(model)*glm::vec4(center,1));
        startPosition=positionNm;startRotation=rotationDegrees;
        rayDistance=glm::distance(pose.position,grabPoint);
    }
    void update(const HandPose& pose) {
        auto frame=glm::mat3(startModel)*axes;
        for(int i=0;i<3;++i)frame[i]=glm::normalize(frame[i]);
        if(rotating) {
            const auto turn=glm::mat3_cast(pose.orientation*glm::inverse(glm::quat_cast(glm::mat3(startHand))));
            rotationDegrees=glm::degrees(glm::eulerAngles(glm::quat_cast(glm::transpose(frame)*turn*frame*glm::mat3_cast(glm::quat(glm::radians(startRotation))))));
            if(snap)rotationDegrees=glm::round(rotationDegrees/15.F)*15.F;
        } else {
            const auto start=glm::vec3(startHand*glm::vec4(0,0,-rayDistance,1));
            const auto end=pose.position+pose.orientation*glm::vec3(0,0,-rayDistance);
            positionNm=startPosition+glm::transpose(axes)*glm::vec3(glm::inverse(startModel)*glm::vec4(end-start,0))/nmScale;
            positionNm=glm::round(positionNm*1000.F)/1000.F;
        }
    }
};
}
