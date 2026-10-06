#include "scrywrite_witness.hpp"
#include "sidebar_menu.hpp"

#include <cstdlib>
#include <iostream>
#include <sstream>
#include <string>

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}

}  // namespace

int main() {
    std::istringstream source(
        "SCRYWRITE_WITNESS 1\n"
        "head 0 1.6 0 1 0 0 0\n"
        "pose right 0.2 1.2 -0.3 1 0 0 0\n"
        "button right menu down\n"
        "step 2\n"
        "button right menu up\n"
        "expect menu sidebars\n"
        "aim_menu right right_tools_[tab:tools]\n"
        "step 1\n"
        "expect hover right_tools_[tab:tools]\n");
    auto replay = nadoc_vr::scrywrite::WitnessReplay::load(source);
    replay.advance({"closed", "none"});
    require(replay.input().menuPressed[1], "menu button should be injected");
    replay.advance({"closed", "none"});
    replay.advance({"sidebars", "none"});
    replay.advance({"sidebars", "none"});
    require(replay.pendingAim().has_value(), "semantic menu aim should be requested");
    replay.resolveAim(glm::quat(1.0F, 0.0F, 0.0F, 0.0F));
    replay.advance({"sidebars", "right_tools_[tab:tools]"});
    replay.advance({"sidebars", "right_tools_[tab:tools]"});
    require(replay.finished(), "matching observation should finish replay");
    require(!replay.failed(), "matching observation should pass");

    std::istringstream failureSource(
        "SCRYWRITE_WITNESS 1\n"
        "expect menu sidebars\n");
    auto failure = nadoc_vr::scrywrite::WitnessReplay::load(failureSource);
    failure.advance({"closed", "none"});
    require(failure.failed(), "menu mismatch should fail and pause");
    require(failure.paused(), "failed replay should remain inspectable");
    require(failure.error().find("expected menu sidebars") != std::string::npos,
            "menu mismatch should be diagnostic");

    std::istringstream stateSource(
        "SCRYWRITE_WITNESS 1\n"
        "expect tool move_rotate\n"
        "expect status select_target\n");
    auto stateReplay = nadoc_vr::scrywrite::WitnessReplay::load(stateSource);
    stateReplay.advance({"closed", "none", "move_rotate", "SELECT TARGET"});
    require(stateReplay.finished() && !stateReplay.failed(),
            "live tool and status observations should be assertable");

    std::istringstream layoutSource(
        "SCRYWRITE_WITNESS 1\n"
        "expect layout valid\n");
    auto layoutReplay = nadoc_vr::scrywrite::WitnessReplay::load(layoutSource);
    layoutReplay.advance({
        "sidebars", "none", "none", "none", "following", {},
        "text_overflow", "text_overflow[title] text escapes its owning bounds",
    });
    require(layoutReplay.failed(), "menu layout assertions should fail semantically");
    require(layoutReplay.error().find("text_overflow[title]") != std::string::npos,
            "layout failures should retain the renderer-native diagnostic");

    std::istringstream liveDisplaySource(
        "SCRYWRITE_WITNESS 1\n"
        "expect display submitted\n"
        "expect tracking tracked\n"
        "expect overlay visible\n"
        "expect framing valid\n");
    auto liveDisplayReplay =
        nadoc_vr::scrywrite::WitnessReplay::load(liveDisplaySource);
    liveDisplayReplay.advance({
        "sidebars", "none", "none", "none", "following", {}, "valid", "",
        "submitted", "tracked", "visible", "valid",
    });
    require(liveDisplayReplay.finished() && !liveDisplayReplay.failed(),
            "submitted-eye, tracking, and overlay provenance should be assertable");

    std::istringstream representationSource(
        "SCRYWRITE_WITNESS 1\n"
        "expect representation ballstick\n");
    auto representationReplay =
        nadoc_vr::scrywrite::WitnessReplay::load(representationSource);
    representationReplay.advance({
        "sidebars", "none", "none", "none", "following", {}, "valid", "",
        "submitted", "tracked", "visible", "valid", "ballstick",
    });
    require(representationReplay.finished() && !representationReplay.failed(),
            "the native representation should be assertable after a menu choice");

    std::istringstream fallbackSource(
        "SCRYWRITE_WITNESS 1\n"
        "expect display submitted\n");
    auto fallbackReplay = nadoc_vr::scrywrite::WitnessReplay::load(fallbackSource);
    fallbackReplay.advance({
        "sidebars", "none", "none", "none", "following", {}, "valid", "",
        "fallback", "tracked", "visible",
    });
    require(fallbackReplay.failed() &&
                fallbackReplay.error().find("got fallback") != std::string::npos,
            "a spectator fallback should not masquerade as a submitted eye");

    std::istringstream snapshotSource(
        "SCRYWRITE_WITNESS 1\n"
        "snapshot sidebar_open\n"
        "expect menu sidebars\n");
    auto snapshotReplay = nadoc_vr::scrywrite::WitnessReplay::load(snapshotSource);
    snapshotReplay.advance({"sidebars"});
    require(snapshotReplay.pendingSnapshot().has_value() &&
                snapshotReplay.pendingSnapshot()->name == "sidebar_open",
            "named actor-eye snapshots should pause replay until captured");
    snapshotReplay.advance({"closed"});
    require(!snapshotReplay.finished(),
            "a pending snapshot should prevent later assertions from advancing");
    snapshotReplay.resolveSnapshot();
    snapshotReplay.advance({"sidebars"});
    require(snapshotReplay.finished() && !snapshotReplay.failed(),
            "replay should continue after a successful actor-eye capture");

    bool unsafeSnapshotRejected = false;
    try {
        std::istringstream unsafe(
            "SCRYWRITE_WITNESS 1\n"
            "snapshot ../escape\n");
        (void)nadoc_vr::scrywrite::WitnessReplay::load(unsafe);
    } catch (const std::exception&) {
        unsafeSnapshotRejected = true;
    }
    require(unsafeSnapshotRejected,
            "snapshot names should not permit path traversal");

    std::istringstream heldFailureSource(
        "SCRYWRITE_WITNESS 1\n"
        "button right trigger down\n"
        "expect menu sidebars\n");
    auto heldFailure = nadoc_vr::scrywrite::WitnessReplay::load(heldFailureSource);
    heldFailure.advance({"closed", "none"});
    require(heldFailure.failed(), "held-input assertion mismatch should fail");
    require(!heldFailure.input().triggerPressed[1],
            "failed replay must neutralize held scripted input");

    std::istringstream placementSource(
        "SCRYWRITE_WITNESS 1\n"
        "pose left -0.2 1.2 -0.3 1 0 0 0\n"
        "touch_menu left right\n"
        "expect placement docked\n"
        "expect menu_moved 0.20\n");
    auto placementReplay = nadoc_vr::scrywrite::WitnessReplay::load(placementSource);
    placementReplay.advance({"sidebars", "none", "none", "none", "following", {}});
    require(placementReplay.pendingMenuTouch().has_value(),
            "semantic menu-edge touch should be requested");
    nadoc_vr::MenuPlacement placement;
    std::array<nadoc_vr::HandPose, 2> placementHands{};
    placementHands[1] = {true, false, {0.2F, 1.2F, -0.3F}, {1, 0, 0, 0}};
    placement.open(1, placementHands, {0, 1.2F, -1}, {1, 0, 0, 0});
    const glm::vec2 menuMinimum=nadoc_vr::kSidebarBounds.minimum;
    const glm::vec2 menuMaximum=nadoc_vr::kSidebarBounds.maximum;
    nadoc_vr::scrywrite::resolveWitnessMenuTouch(
        placementReplay, placement, menuMinimum, menuMaximum, true);
    require(!placementReplay.pendingMenuTouch(),
            "live menu placement should resolve the semantic edge");
    require(glm::length(
        placementReplay.input().hands[0].position + glm::vec3(0,0,-.12F) -
        placement.worldPoint({menuMaximum.x, (menuMinimum.y+menuMaximum.y)*.5F, 0.0F})) < 1.0e-6F,
        "touch_menu should put the requested selection sphere on the live menu border");
    placementReplay.advance({
        "sidebars", "none", "none", "none", "docked",
        placement.position() + glm::vec3(0.25F, 0.0F, 0.0F),
    });
    require(placementReplay.finished() && !placementReplay.failed(),
            "docked and displaced live menu should satisfy placement assertions");

    std::istringstream missingMenuSource(
        "SCRYWRITE_WITNESS 1\n"
        "pose left -0.2 1.2 -0.3 1 0 0 0\n"
        "touch_menu left top\n");
    auto missingMenu = nadoc_vr::scrywrite::WitnessReplay::load(missingMenuSource);
    missingMenu.advance({});
    nadoc_vr::scrywrite::resolveWitnessMenuTouch(
        missingMenu, placement, menuMinimum, menuMaximum, false);
    require(missingMenu.failed() && missingMenu.error().find("open menu") != std::string::npos,
            "touch_menu should fail closed when no live menu exists");

    const std::vector<nadoc_vr::scrywrite::WitnessMenuEntry> entries = {
        {"MOVE ROTATE", 1, {0.0F, 1.0F, -1.0F}},
        {"TOOLS", 15, {0.2F, 1.0F, -1.0F}},
    };
    require(nadoc_vr::scrywrite::findWitnessMenuEntry(entries, "move_rotate").has_value(),
            "semantic menu labels should normalize consistently");
    require(nadoc_vr::scrywrite::witnessHoverLabel(entries, 15) == "tools",
            "production hit ids should map back to semantic labels");
    auto playbackEntries=entries;
    playbackEntries.front().label="LEFT / Frame 8 / 20 [trajectory:seek]";
    playbackEntries.front().id="trajectory:seek";
    require(nadoc_vr::scrywrite::findWitnessMenuEntry(playbackEntries,"trajectory:seek").has_value(),
            "dynamic sidebar labels must remain aimable through their stable control id");
    require(!nadoc_vr::scrywrite::findWitnessMenuEntry(playbackEntries,"missing-control"),
            "unknown control ids must fail closed");
    const auto aim = nadoc_vr::scrywrite::witnessAimOrientation(
        {0.0F, 1.0F, 0.0F}, {0.0F, 1.0F, -1.0F});
    require(aim.has_value(), "a separated target should produce an aim orientation");
    require(glm::length(*aim * glm::vec3(0.0F, 0.0F, -1.0F) -
                        glm::vec3(0.0F, 0.0F, -1.0F)) < 1.0e-6F,
            "aim orientation should point controller negative-z at the target");
    const auto frustum = nadoc_vr::scrywrite::witnessHeadFrustum({});
    require(frustum.size() == 8,
            "actor head guide should contain four rays and four edges");
    require(std::abs(std::abs(frustum[0].second.x) - 0.284F) < 1.0e-6F &&
                std::abs(std::abs(frustum[0].second.y - 1.6F) - 0.160F) < 1.0e-6F,
            "actor head guide should match the 72-degree 16:9 capture frustum");

    std::cout << "ScryWrite witness tests passed\n";
    return 0;
}
