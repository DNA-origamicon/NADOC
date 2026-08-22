#include "spectator_mirror.hpp"

#include <cstdlib>
#include <iostream>

namespace {

void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "FAIL: " << message << '\n';
        std::exit(1);
    }
}

}  // namespace

int main() {
    using nadoc_vr::SpectatorMirrorEye;
    require(nadoc_vr::parseSpectatorMirrorEye("left") == SpectatorMirrorEye::left,
            "left eye option should parse");
    require(nadoc_vr::parseSpectatorMirrorEye("right") == SpectatorMirrorEye::right,
            "right eye option should parse");
    require(!nadoc_vr::parseSpectatorMirrorEye("cyclops"),
            "unknown mirror eye should fail closed");
    require(nadoc_vr::spectatorMirrorViewIndex(SpectatorMirrorEye::left, 2) == 0U,
            "left eye should select the first stereo view");
    require(nadoc_vr::spectatorMirrorViewIndex(SpectatorMirrorEye::right, 2) == 1U,
            "right eye should select the second stereo view");
    require(!nadoc_vr::spectatorMirrorViewIndex(SpectatorMirrorEye::right, 1),
            "right eye should not silently alias a mono view");
    require(!nadoc_vr::spectatorMirrorViewIndex(SpectatorMirrorEye::off, 2),
            "disabled mirror should select no view");

    const auto pillarbox = nadoc_vr::fitSpectatorMirrorViewport(1000, 1000, 1600, 900);
    require(pillarbox.x == 350 && pillarbox.y == 0 &&
                pillarbox.width == 900 && pillarbox.height == 900,
            "square eye image should be centered with pillarboxing");
    const auto letterbox = nadoc_vr::fitSpectatorMirrorViewport(1600, 900, 1000, 1000);
    require(letterbox.x == 0 && letterbox.y == 218 &&
                letterbox.width == 1000 && letterbox.height == 563,
            "wide eye image should be centered with letterboxing");
    require(nadoc_vr::fitSpectatorMirrorViewport(0, 900, 1000, 1000).width == 0,
            "invalid dimensions should fail closed to an empty viewport");
    require(nadoc_vr::spectatorMirrorWindowTitle(SpectatorMirrorEye::left).find(
                "HMD LEFT | WAITING FOR FIRST FRAME") != std::string::npos,
            "initial mirror title should identify the selected eye without claiming a source");
    nadoc_vr::SpectatorMirrorTelemetry telemetry;
    telemetry.frame = 123;
    telemetry.motion = 4;
    telemetry.poseValid = true;
    telemetry.poseTracked = true;
    telemetry.x = 0.125F;
    telemetry.yawDegrees = -45.0F;
    telemetry.pixelSample = 7;
    telemetry.pixelStatus = nadoc_vr::SpectatorPixelStatus::frozen_suspected;
    telemetry.coverageStatus = nadoc_vr::SpectatorCoverageStatus::grid_only;
    telemetry.placementApplied = true;
    telemetry.placementOrientation = "TOP";
    const auto title = nadoc_vr::spectatorMirrorTelemetryTitle(
        SpectatorMirrorEye::left, true, telemetry);
    require(title.find("F123 M4") != std::string::npos &&
                title.find("SPECTATOR FALLBACK") != std::string::npos &&
                title.find("TRACKED") != std::string::npos &&
                title.find("GRID ONLY | O TOP | PX FROZEN?") != std::string::npos &&
                title.find("| GRID") != std::string::npos,
            "live title should expose frame, motion, tracking, and diagnostic mode");
    telemetry.submittedEye = true;
    const auto submittedTitle = nadoc_vr::spectatorMirrorTelemetryTitle(
        SpectatorMirrorEye::right, false, telemetry);
    require(submittedTitle.find("HMD RIGHT | SUBMITTED") != std::string::npos &&
                submittedTitle.find(
                    "SUBMITTED | GRID ONLY | O TOP | PX FROZEN? | TRACKED") !=
                    std::string::npos &&
                submittedTitle.find("YP -45.0 0.0 | F123 M4") != std::string::npos &&
                submittedTitle.find("ROOM GRID") == std::string::npos,
            "submitted title should prioritize source, pixel status, tracking, and orientation");
    require(nadoc_vr::spectatorMirrorHeartbeatHigh(0) &&
                !nadoc_vr::spectatorMirrorHeartbeatHigh(15) &&
                nadoc_vr::spectatorMirrorHeartbeatHigh(30),
            "desktop-only heartbeat should alternate every fifteen frames");
    require(!nadoc_vr::spectatorPoseReadyForPlacement(true, true, false, false) &&
                !nadoc_vr::spectatorPoseReadyForPlacement(true, true, true, false) &&
                nadoc_vr::spectatorPoseReadyForPlacement(true, true, true, true),
            "one-shot placement must wait for a fully tracked pose");
    nadoc_vr::SpectatorPlacementGate placementGate;
    require(!placementGate.observe(false, false, 0.0F, 0.0F),
            "an untracked startup pose must not advance placement");
    for (int sample = 0; sample < 14; ++sample) {
        require(!placementGate.observe(
                    true, sample > 0, 0.001F, 0.1F),
                "placement must wait for a stable tracked window");
    }
    require(placementGate.observe(true, true, 0.001F, 0.1F),
            "fifteen stable tracked poses should release placement");
    require(!placementGate.observe(true, true, 0.50F, 0.1F),
            "a large startup discontinuity must reset the placement gate");

    std::cout << "NADOC VR spectator mirror tests passed\n";
    return 0;
}
