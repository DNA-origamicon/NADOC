#pragma once
#include <cmath>
#include <optional>
#include <glm/glm.hpp>
#include <glm/gtc/quaternion.hpp>

namespace nadoc_vr {
struct SourceRigidPlacement {
    glm::vec3 translationNanometers;
    glm::quat rotation;
};
// Convert a desired canonical frame pose in tracking space back to source space.
// Presentation must be an orientation-preserving uniform similarity transform.
// Molecular axes/cells are constructed separately in their canonical plane.
inline std::optional<SourceRigidPlacement> trackingToSourcePlacement(
    const glm::vec3& worldOrigin, const glm::quat& worldOrientation,
    const glm::mat4& modelToWorld, const glm::vec3& sourceCenter,
    float normalizationScale, const glm::vec3& normalizedOffset) {
    const auto finite3 = [](const glm::vec3& p) {
        return std::isfinite(p.x) && std::isfinite(p.y) && std::isfinite(p.z);
    };
    if (!finite3(worldOrigin) || !finite3(sourceCenter) || !finite3(normalizedOffset) ||
        !std::isfinite(normalizationScale) || normalizationScale <= 0) return std::nullopt;
    for (int c=0;c<4;++c) for (int r=0;r<4;++r)
        if (!std::isfinite(modelToWorld[c][r])) return std::nullopt;
    if (std::abs(modelToWorld[0][3])>1e-6F || std::abs(modelToWorld[1][3])>1e-6F ||
        std::abs(modelToWorld[2][3])>1e-6F || std::abs(modelToWorld[3][3]-1)>1e-6F) return std::nullopt;
    const float scale = glm::length(glm::vec3(modelToWorld[0]));
    if (!std::isfinite(scale) || scale < 1e-8F) return std::nullopt;
    const glm::mat3 rotation = glm::mat3(modelToWorld)/scale;
    const glm::mat3 gram = glm::transpose(rotation)*rotation;
    for (int c=0;c<3;++c) for (int r=0;r<3;++r)
        if (std::abs(gram[c][r]-(c==r ? 1.F : 0.F))>1e-4F) return std::nullopt;
    if (glm::determinant(rotation)<0) return std::nullopt;
    const float qLength = glm::length(worldOrientation);
    if (!std::isfinite(qLength) || qLength<1e-8F) return std::nullopt;
    const glm::vec3 local = glm::vec3(glm::inverse(modelToWorld)*glm::vec4(worldOrigin,1));
    const glm::vec3 source = (local-normalizedOffset)/normalizationScale+sourceCenter;
    if (!finite3(source)) return std::nullopt;
    return SourceRigidPlacement{source, glm::normalize(
        glm::conjugate(glm::quat_cast(rotation))*glm::normalize(worldOrientation))};
}
}
