#pragma once

#include "spectator_diagnostics.hpp"

#include <algorithm>
#include <cstdint>
#include <optional>
#include <iomanip>
#include <sstream>
#include <string>

namespace nadoc_vr {

enum class SpectatorMirrorEye { off, left, right };

struct SpectatorMirrorViewport {
    int32_t x = 0;
    int32_t y = 0;
    int32_t width = 0;
    int32_t height = 0;
};

struct SpectatorMirrorTelemetry {
    uint64_t frame = 0;
    uint64_t motion = 0;
    bool poseValid = false;
    bool poseTracked = false;
    bool submittedEye = false;
    float x = 0.0F;
    float y = 0.0F;
    float z = 0.0F;
    float yawDegrees = 0.0F;
    float pitchDegrees = 0.0F;
    uint64_t pixelSample = 0;
    SpectatorPixelStatus pixelStatus = SpectatorPixelStatus::unavailable;
    SpectatorCoverageStatus coverageStatus = SpectatorCoverageStatus::unavailable;
    bool placementApplied = false;
    std::string placementOrientation;
    float nonBlackFraction = 0.0F;
    float changedFraction = 0.0F;
};

inline std::optional<SpectatorMirrorEye> parseSpectatorMirrorEye(
    const std::string& value) {
    if (value == "off") return SpectatorMirrorEye::off;
    if (value == "left") return SpectatorMirrorEye::left;
    if (value == "right") return SpectatorMirrorEye::right;
    return std::nullopt;
}

inline const char* spectatorMirrorEyeName(SpectatorMirrorEye eye) {
    if (eye == SpectatorMirrorEye::left) return "left";
    if (eye == SpectatorMirrorEye::right) return "right";
    return "off";
}

inline std::optional<uint32_t> spectatorMirrorViewIndex(
    SpectatorMirrorEye eye, uint32_t viewCount) {
    if (eye == SpectatorMirrorEye::off) return std::nullopt;
    if (eye == SpectatorMirrorEye::left) {
        return viewCount >= 1U ? std::optional<uint32_t>(0U) : std::nullopt;
    }
    return viewCount >= 2U ? std::optional<uint32_t>(1U) : std::nullopt;
}

inline SpectatorMirrorViewport fitSpectatorMirrorViewport(
    int32_t sourceWidth, int32_t sourceHeight,
    int32_t destinationWidth, int32_t destinationHeight) {
    if (sourceWidth <= 0 || sourceHeight <= 0 ||
        destinationWidth <= 0 || destinationHeight <= 0) {
        return {};
    }
    const double sourceAspect = static_cast<double>(sourceWidth) / sourceHeight;
    const double destinationAspect =
        static_cast<double>(destinationWidth) / destinationHeight;
    SpectatorMirrorViewport result;
    if (destinationAspect > sourceAspect) {
        result.height = destinationHeight;
        result.width = std::max<int32_t>(
            1, static_cast<int32_t>(destinationHeight * sourceAspect + 0.5));
        result.x = (destinationWidth - result.width) / 2;
    } else {
        result.width = destinationWidth;
        result.height = std::max<int32_t>(
            1, static_cast<int32_t>(destinationWidth / sourceAspect + 0.5));
        result.y = (destinationHeight - result.height) / 2;
    }
    return result;
}

inline std::string spectatorMirrorWindowTitle(SpectatorMirrorEye eye) {
    if (eye == SpectatorMirrorEye::off) {
        return "NADOC VR companion";
    }
    std::string title = "NADOC HMD ";
    title += eye == SpectatorMirrorEye::left ? "LEFT" : "RIGHT";
    title += " | WAITING FOR FIRST FRAME";
    return title;
}

inline bool spectatorMirrorHeartbeatHigh(uint64_t frame) {
    return ((frame / 15U) % 2U) == 0U;
}

inline bool spectatorPoseReadyForPlacement(
    bool positionValid, bool orientationValid,
    bool positionTracked, bool orientationTracked) {
    return positionValid && orientationValid &&
           positionTracked && orientationTracked;
}

struct SpectatorPlacementGate {
    uint32_t stableSamples = 0U;

    bool observe(bool fullyTracked, bool hasPrevious,
                 float translationMeters, float rotationDegrees) {
        constexpr uint32_t kRequiredStableSamples = 15U;
        constexpr float kMaximumStepMeters = 0.05F;
        constexpr float kMaximumStepDegrees = 5.0F;
        if (!fullyTracked) {
            stableSamples = 0U;
            return false;
        }
        if (!hasPrevious || translationMeters > kMaximumStepMeters ||
            rotationDegrees > kMaximumStepDegrees) {
            stableSamples = 1U;
        } else if (stableSamples < kRequiredStableSamples) {
            ++stableSamples;
        }
        return stableSamples >= kRequiredStableSamples;
    }
};

inline std::string spectatorMirrorTelemetryTitle(
    SpectatorMirrorEye eye, bool roomGrid,
    const SpectatorMirrorTelemetry& telemetry) {
    std::ostringstream title;
    title << "NADOC HMD "
          << (eye == SpectatorMirrorEye::right ? "RIGHT" : "LEFT")
          << " | " << (telemetry.submittedEye ? "SUBMITTED" : "SPECTATOR FALLBACK");
    if (telemetry.coverageStatus != SpectatorCoverageStatus::unavailable) {
        title << " | " << spectatorCoverageStatusName(telemetry.coverageStatus);
    }
    if (telemetry.placementApplied && !telemetry.placementOrientation.empty()) {
        title << " | O " << telemetry.placementOrientation;
    }
    // Keep the highest-value failure cue near the front: desktop title bars often
    // truncate the pose tail on the default 960 px companion window.
    if (telemetry.pixelStatus != SpectatorPixelStatus::unavailable) {
        title << " | PX " << spectatorPixelStatusName(telemetry.pixelStatus);
    }
    title << " | ";
    if (!telemetry.poseValid) title << "POSE INVALID";
    else title << (telemetry.poseTracked ? "TRACKED" : "VALID NOT TRACKED");
    title << std::fixed << std::setprecision(1)
          << " | YP " << telemetry.yawDegrees << ' ' << telemetry.pitchDegrees
          << " | F" << telemetry.frame << " M" << telemetry.motion;
    if (roomGrid) title << " | GRID";
    return title.str();
}

}  // namespace nadoc_vr
