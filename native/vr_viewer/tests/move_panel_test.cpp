#include "move_panel.hpp"
#include <cassert>
int main() {
    using namespace nadoc_vr;
    // The presentation includes inverse desktop rotation, headset yaw, translation
    // and scale. Controller motion must still be a rigid world-space delta.
    for(const auto basis:{glm::mat3(1),glm::mat3_cast(glm::quat(glm::vec3(.7F,-1.1F,.4F)))}) {
        SceneManipulator scene;
        scene.placeAtRoomOrigin({0,1.7F,1.5F},glm::quat(glm::vec3(.3F,.8F,-.2F)),
            glm::mat4(1),{0,0,-1.3F},basis);
        const auto model=scene.transform();
        const glm::vec3 point(.1F,-.2F,-1.1F);
        const auto world=glm::vec3(model*glm::vec4(point,1));
        const glm::vec3 pivot(.3F,1.1F,-.2F),translation(.07F,-.03F,.11F);
        HandPose start;start.valid=true;start.position=pivot+glm::vec3(.05F,.02F,0);
        start.orientation=glm::quat(glm::vec3(.1F,-.4F,.2F));
        auto end=start;const auto turn=glm::angleAxis(.7F,glm::normalize(glm::vec3(1,2,3)));
        end.position+=translation;end.orientation=turn*start.orientation;
        MovePanel move;move.begin(1,start,model,pivot);
        const auto actual=glm::vec3(model*move.delta(end)*glm::vec4(point,1));
        assert(glm::distance(actual,pivot+translation+turn*(world-pivot))<1e-5F);
    }
    MovePanel panel;
    HandPose hand;hand.valid=true;hand.position={.03F,0,0};
    const glm::vec3 pivot{0,0,0};
    panel.begin(1,hand,glm::mat4(1),pivot);
    hand.orientation=glm::angleAxis(glm::radians(90.F),glm::vec3(0,0,1));
    hand.position += glm::vec3(.1F,.2F,0);
    const auto delta=panel.delta(hand);
    assert(glm::distance(glm::vec3(delta*glm::vec4(pivot,1)),glm::vec3(.1F,.2F,0))<1e-5F);
    assert(glm::distance(glm::vec3(delta*glm::vec4(1,0,0,0)),glm::vec3(0,1,0))<1e-5F);
    std::array<SidebarMenu,2> menus{SidebarMenu(0),SidebarMenu(1)};
    panel.hand.reset();
    assert(panel.selectionEnabled(0) && panel.selectionEnabled(1));
    panel.enter(menus);panel.refresh(menus,"base","READY");
    assert(panel.selectionEnabled(0) && !panel.selectionEnabled(1));
    const auto controls=menus[1].controls();
    assert(std::none_of(controls.begin(),controls.end(),[](const auto& c){return c.id=="move:selection" || c.id=="move:base" || c.id=="move:domain" || c.id=="move:cluster";}));
    assert(std::any_of(controls.begin(),controls.end(),[](const auto& c){return c.id=="move:undo";}));
    panel.begin(0,hand,glm::mat4(1),pivot);assert(!panel.hand);
    panel.begin(1,hand,glm::mat4(1),pivot);assert(panel.hand==1);
    assert(!panel.selectionEnabled(0) && !panel.selectionEnabled(1));
    panel.exit(menus);assert(panel.selectionEnabled(0) && panel.selectionEnabled(1));
    assert(ToolShell::supportsSelection(ToolMode::move_rotate,"overhang"));
}
