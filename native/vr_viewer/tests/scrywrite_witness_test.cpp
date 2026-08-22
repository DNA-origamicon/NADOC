#include "scrywrite_witness.hpp"

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
        "expect menu options\n"
        "aim_menu right tools\n"
        "step 1\n"
        "expect hover tools\n");
    auto replay = nadoc_vr::scrywrite::WitnessReplay::load(source);
    replay.advance({"closed", "none"});
    require(replay.input().menuPressed[1], "menu button should be injected");
    replay.advance({"closed", "none"});
    replay.advance({"options", "none"});
    replay.advance({"options", "none"});
    require(replay.pendingAim().has_value(), "semantic menu aim should be requested");
    replay.resolveAim(glm::quat(1.0F, 0.0F, 0.0F, 0.0F));
    replay.advance({"options", "tools"});
    replay.advance({"options", "tools"});
    require(replay.finished(), "matching observation should finish replay");
    require(!replay.failed(), "matching observation should pass");

    std::istringstream failureSource(
        "SCRYWRITE_WITNESS 1\n"
        "expect menu tools\n");
    auto failure = nadoc_vr::scrywrite::WitnessReplay::load(failureSource);
    failure.advance({"closed", "none"});
    require(failure.failed(), "menu mismatch should fail and pause");
    require(failure.paused(), "failed replay should remain inspectable");
    require(failure.error().find("expected menu tools") != std::string::npos,
            "menu mismatch should be diagnostic");

    std::istringstream stateSource(
        "SCRYWRITE_WITNESS 1\n"
        "expect tool move_rotate\n"
        "expect status select_target\n");
    auto stateReplay = nadoc_vr::scrywrite::WitnessReplay::load(stateSource);
    stateReplay.advance({"closed", "none", "move_rotate", "SELECT TARGET"});
    require(stateReplay.finished() && !stateReplay.failed(),
            "live tool and status observations should be assertable");

    std::istringstream heldFailureSource(
        "SCRYWRITE_WITNESS 1\n"
        "button right trigger down\n"
        "expect menu tools\n");
    auto heldFailure = nadoc_vr::scrywrite::WitnessReplay::load(heldFailureSource);
    heldFailure.advance({"closed", "none"});
    require(heldFailure.failed(), "held-input assertion mismatch should fail");
    require(!heldFailure.input().triggerPressed[1],
            "failed replay must neutralize held scripted input");

    const std::vector<nadoc_vr::scrywrite::WitnessMenuEntry> entries = {
        {"MOVE ROTATE", 1, {0.0F, 1.0F, -1.0F}},
        {"TOOLS", 15, {0.2F, 1.0F, -1.0F}},
    };
    require(nadoc_vr::scrywrite::findWitnessMenuEntry(entries, "move_rotate").has_value(),
            "semantic menu labels should normalize consistently");
    require(nadoc_vr::scrywrite::witnessHoverLabel(entries, 15) == "tools",
            "production hit ids should map back to semantic labels");
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
