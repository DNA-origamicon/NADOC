#include "move_panel.hpp"
#include <cassert>
int main() {
    using namespace nadoc_vr;
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
    panel.enter(menus);panel.refresh(menus,"base","READY");
    assert(ToolShell::supportsSelection(ToolMode::move_rotate,"overhang"));
}
