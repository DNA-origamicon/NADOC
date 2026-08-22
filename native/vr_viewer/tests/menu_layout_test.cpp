#include "menu_layout.hpp"

#include <cstdlib>
#include <iostream>
#include <string>

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}

bool hasIssue(const nadoc_vr::MenuLayoutAudit& audit, const std::string& code) {
    return std::any_of(
        audit.issues().begin(), audit.issues().end(),
        [&](const auto& issue) { return issue.code == code; });
}

}  // namespace

int main() {
    using nadoc_vr::MenuPanelBounds;
    const MenuPanelBounds panel{{-0.32F, -0.545F}, {0.32F, 0.33F}};
    const MenuPanelBounds visual{{-0.305F, 0.112F}, {-0.015F, 0.158F}};
    const MenuPanelBounds hit{{-0.305F, 0.110F}, {-0.015F, 0.160F}};

    nadoc_vr::MenuLayoutAudit normal;
    normal.reset(panel);
    normal.addControl("tools", visual, hit);
    const auto normalText = normal.fitAndAddText(
        "tools.label", "TOOLS", -0.293F, 0.147F, 0.0036F, visual);
    require(normalText.scale == 0.0036F, "ordinary control text should retain its scale");
    require(normal.valid(), "ordinary menu geometry should pass the audit");

    nadoc_vr::MenuLayoutAudit overflow;
    overflow.reset(panel);
    overflow.addText(
        "title", "A NAME THAT IS FAR TOO LONG FOR THIS MENU", -0.30F, 0.305F,
        0.006F, panel);
    require(hasIssue(overflow, "text_overflow"),
            "an unfitted long title should trip the overflow oracle");

    nadoc_vr::MenuLayoutAudit unreadable;
    unreadable.reset(panel);
    unreadable.fitAndAddText(
        "title", std::string(100U, 'W'), -0.30F, 0.305F, 0.006F, panel);
    require(hasIssue(unreadable, "text_undersized"),
            "a long title shrunk below the scale floor should trip the readability oracle");
    require(!hasIssue(unreadable, "text_overflow"),
            "fitted text should remain geometrically contained");

    nadoc_vr::MenuLayoutAudit wrongHitbox;
    wrongHitbox.reset(panel);
    wrongHitbox.addControl(
        "tools", visual, {{-0.20F, 0.120F}, {-0.05F, 0.150F}});
    require(hasIssue(wrongHitbox, "hitbox_mismatch"),
            "a hitbox smaller than its drawn control should be rejected");
    require(hasIssue(wrongHitbox, "target_undersized"),
            "an undersized hit target should be rejected independently");

    nadoc_vr::MenuLayoutAudit overlap;
    overlap.reset(panel);
    overlap.addControl("first", visual, hit);
    overlap.addControl(
        "second", {{-0.02F, 0.112F}, {0.27F, 0.158F}},
        {{-0.02F, 0.110F}, {0.27F, 0.160F}});
    require(hasIssue(overlap, "hitbox_overlap"),
            "overlapping interactive regions should be rejected");

    nadoc_vr::MenuLayoutAudit outside;
    outside.reset(panel);
    outside.addControl(
        "off_panel", {{0.20F, 0.10F}, {0.40F, 0.15F}},
        {{0.20F, 0.10F}, {0.40F, 0.15F}});
    require(hasIssue(outside, "control_overflow"),
            "a drawn control outside the panel should be rejected");

    const std::array<glm::vec3, 4> framedCorners{{
        {-0.30F, 0.30F, -1.0F}, {-0.30F, -0.30F, -1.0F},
        {0.30F, 0.30F, -1.0F}, {0.30F, -0.30F, -1.0F},
    }};
    require(nadoc_vr::assessActorEyePanelFraming(
                framedCorners, {}, {1.0F, 0.0F, 0.0F, 0.0F}).status() == "valid",
            "a complete panel in front of the actor should pass framing");
    auto clippedCorners = framedCorners;
    for (auto& corner : clippedCorners) corner.x += 1.4F;
    require(nadoc_vr::assessActorEyePanelFraming(
                clippedCorners, {}, {1.0F, 0.0F, 0.0F, 0.0F}).status() == "clipped",
            "a panel outside the actor frustum should trip the framing oracle");
    auto behindCorners = framedCorners;
    for (auto& corner : behindCorners) corner.z = 1.0F;
    require(nadoc_vr::assessActorEyePanelFraming(
                behindCorners, {}, {1.0F, 0.0F, 0.0F, 0.0F}).status() == "behind",
            "a panel behind the actor should trip the framing oracle");

    std::cout << "Menu layout audit tests passed\n";
    return 0;
}
