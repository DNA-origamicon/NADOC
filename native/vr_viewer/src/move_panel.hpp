#pragma once
#include "sidebar_menu.hpp"
namespace nadoc_vr {
class MovePanel {
 public:
    static constexpr size_t selectHand=0, moveHand=1;
    bool active=false;
    bool selectionEnabled(size_t h) const { return !active || (h==selectHand && !hand); }
    size_t savedOffset=0;
    std::optional<size_t> hand;
    std::array<bool,2> nearby{};
    glm::mat4 startHand{1},startModel{1};
    glm::vec3 pivot{},grabPoint{};
    std::optional<glm::vec3> beamEnd;
    void enter(std::array<SidebarMenu,2>& menus) {
        if(!active)savedOffset=menus[1].offset();
        active=true;menus[1].open=true;menus[1].offsets[menus[1].selected]=0;
        menus[1].focus.reset();
    }
    void exit(std::array<SidebarMenu,2>& menus) {
        active=false;hand.reset();nearby.fill(false);beamEnd.reset();
        auto& m=menus[1];m.customTab.reset();m.offsets[m.selected]=savedOffset;m.focus.reset();
    }
    void refresh(std::array<SidebarMenu,2>& menus,const std::string& kind,const std::string& status) const {
        if(!active)return;
        SidebarTab tab{1,"move","Move / Rotate",{}};
        auto row=[&](std::string id,std::string label,std::string detail="") {
            tab.rows.push_back({"move:"+id,label,detail,"move:"+id,{}});
        };
        row("back","Move / Rotate - Return",status);
        row("apply","APPLY",kind=="none"?"LEFT TRIGGER SELECTS":"POINT RIGHT / TRIGGER GRABS");
        row("cancel","CANCEL","LEFT SELECTS / RIGHT MOVES / GRIPS MOVE SCENE");
        row("undo","UNDO","HOLD LEFT PAD TO CHOOSE SELECTION");
        row("recenter","Frame model");
        menus[1].customTab=std::move(tab);
    }
    void begin(size_t h,const HandPose& pose,const glm::mat4& model,const glm::vec3& center) {
        if(h!=moveHand)return;
        hand=h;startHand=poseMatrix(pose);startModel=model;pivot=center;
    }
    glm::mat4 delta(const HandPose& pose) const {
        const glm::mat4 current=poseMatrix(pose);
        const glm::vec3 translation=glm::vec3(current[3]-startHand[3]);
        const glm::mat4 rotation=glm::mat4(glm::mat3(current)*glm::inverse(glm::mat3(startHand)));
        // Rotate about the target, independent of where within the grab radius
        // the controller was acquired. There is no scale degree of freedom.
        return glm::inverse(startModel)*glm::translate(glm::mat4(1),pivot+translation)
            *rotation*glm::translate(glm::mat4(1),-pivot)*startModel;
    }
};
}
