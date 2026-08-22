#pragma once

#include <glm/glm.hpp>
#include <glm/gtc/quaternion.hpp>

#include <cmath>
#include <optional>
#include <string>

namespace nadoc_vr {

enum class ScenePlacementView { head, mirror, left, right };

enum class ScenePlacementOrientation {
    front,
    back,
    left,
    right,
    top,
    bottom,
    isometric,
};

struct SceneViewPlacement {
    ScenePlacementView view = ScenePlacementView::mirror;
    ScenePlacementOrientation orientation = ScenePlacementOrientation::front;
    float distanceMeters = 1.30F;
    float scale = 2.0F;
    float yawDegrees = 0.0F;
    float pitchDegrees = 0.0F;
    float rollDegrees = 0.0F;
};

inline std::optional<ScenePlacementView> parseScenePlacementView(
    const std::string& value) {
    if (value == "head") return ScenePlacementView::head;
    if (value == "mirror") return ScenePlacementView::mirror;
    if (value == "left") return ScenePlacementView::left;
    if (value == "right") return ScenePlacementView::right;
    return std::nullopt;
}

inline const char* scenePlacementViewName(ScenePlacementView value) {
    switch (value) {
        case ScenePlacementView::head: return "head";
        case ScenePlacementView::mirror: return "mirror";
        case ScenePlacementView::left: return "left";
        case ScenePlacementView::right: return "right";
    }
    return "mirror";
}

inline std::optional<ScenePlacementOrientation> parseScenePlacementOrientation(
    const std::string& value) {
    if (value == "front" || value == "authored") {
        return ScenePlacementOrientation::front;
    }
    if (value == "back") return ScenePlacementOrientation::back;
    if (value == "left") return ScenePlacementOrientation::left;
    if (value == "right") return ScenePlacementOrientation::right;
    if (value == "top") return ScenePlacementOrientation::top;
    if (value == "bottom") return ScenePlacementOrientation::bottom;
    if (value == "isometric") return ScenePlacementOrientation::isometric;
    return std::nullopt;
}

inline const char* scenePlacementOrientationName(
    ScenePlacementOrientation value) {
    switch (value) {
        case ScenePlacementOrientation::front: return "front";
        case ScenePlacementOrientation::back: return "back";
        case ScenePlacementOrientation::left: return "left";
        case ScenePlacementOrientation::right: return "right";
        case ScenePlacementOrientation::top: return "top";
        case ScenePlacementOrientation::bottom: return "bottom";
        case ScenePlacementOrientation::isometric: return "isometric";
    }
    return "front";
}

inline bool validSceneViewPlacement(const SceneViewPlacement& placement) {
    return std::isfinite(placement.distanceMeters) &&
           placement.distanceMeters >= 0.20F && placement.distanceMeters <= 10.0F &&
           std::isfinite(placement.scale) &&
           placement.scale >= 0.05F && placement.scale <= 20.0F &&
           std::isfinite(placement.yawDegrees) &&
           std::isfinite(placement.pitchDegrees) &&
           std::isfinite(placement.rollDegrees) &&
           std::abs(placement.yawDegrees) <= 360.0F &&
           std::abs(placement.pitchDegrees) <= 360.0F &&
           std::abs(placement.rollDegrees) <= 360.0F;
}

inline glm::quat scenePlacementOrientation(
    const SceneViewPlacement& placement) {
    float presetYaw = 0.0F;
    float presetPitch = 0.0F;
    switch (placement.orientation) {
        case ScenePlacementOrientation::front: break;
        case ScenePlacementOrientation::back: presetYaw = 180.0F; break;
        case ScenePlacementOrientation::left: presetYaw = 90.0F; break;
        case ScenePlacementOrientation::right: presetYaw = -90.0F; break;
        case ScenePlacementOrientation::top: presetPitch = 90.0F; break;
        case ScenePlacementOrientation::bottom: presetPitch = -90.0F; break;
        case ScenePlacementOrientation::isometric:
            presetYaw = -35.0F;
            presetPitch = -20.0F;
            break;
    }
    const glm::quat yaw = glm::angleAxis(
        glm::radians(presetYaw + placement.yawDegrees), glm::vec3(0, 1, 0));
    const glm::quat pitch = glm::angleAxis(
        glm::radians(presetPitch + placement.pitchDegrees), glm::vec3(1, 0, 0));
    const glm::quat roll = glm::angleAxis(
        glm::radians(placement.rollDegrees), glm::vec3(0, 0, 1));
    return glm::normalize(yaw * pitch * roll);
}

}  // namespace nadoc_vr
