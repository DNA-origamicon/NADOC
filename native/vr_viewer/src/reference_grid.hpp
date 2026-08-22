#pragma once

#include <glm/glm.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <stdexcept>
#include <vector>

namespace nadoc_vr {

struct ReferenceGridLine {
    glm::vec3 first{};
    glm::vec3 second{};
    glm::vec3 color{};
};

struct ReferenceGridFace {
    int axis = 0;
    float sign = 1.0F;
    glm::vec3 color{};
};

inline constexpr std::array<ReferenceGridFace, 6> kReferenceGridFaces = {{
    {0, 1.0F, {1.00F, 0.16F, 0.10F}},   // +X red
    {0, -1.0F, {0.10F, 0.95F, 1.00F}},  // -X cyan
    {1, 1.0F, {0.20F, 1.00F, 0.22F}},   // +Y green
    {1, -1.0F, {1.00F, 0.18F, 0.92F}},  // -Y magenta
    {2, 1.0F, {0.38F, 0.58F, 1.00F}},   // +Z blue
    {2, -1.0F, {1.00F, 0.86F, 0.10F}},  // -Z yellow
}};

inline std::vector<ReferenceGridLine> buildRoomReferenceGrid(
    float halfExtentMeters = 2.5F, float spacingMeters = 0.5F) {
    if (!std::isfinite(halfExtentMeters) || !std::isfinite(spacingMeters) ||
        halfExtentMeters <= 0.0F || spacingMeters <= 0.0F ||
        halfExtentMeters > 20.0F || spacingMeters > halfExtentMeters) {
        throw std::invalid_argument("invalid room reference grid dimensions");
    }
    const int intervals = std::max(
        1, static_cast<int>(std::round(2.0F * halfExtentMeters / spacingMeters)));
    const float actualSpacing = 2.0F * halfExtentMeters / intervals;
    std::vector<ReferenceGridLine> lines;
    lines.reserve(static_cast<size_t>(6 * (2 * (intervals + 1) + 2) + 3));
    for (const auto& face : kReferenceGridFaces) {
        const int axisU = (face.axis + 1) % 3;
        const int axisV = (face.axis + 2) % 3;
        const glm::vec3 minorColor = face.color * 0.42F;
        for (int index = 0; index <= intervals; ++index) {
            const float offset = -halfExtentMeters + actualSpacing * index;
            glm::vec3 first{};
            glm::vec3 second{};
            first[face.axis] = second[face.axis] = face.sign * halfExtentMeters;
            first[axisU] = second[axisU] = offset;
            first[axisV] = -halfExtentMeters;
            second[axisV] = halfExtentMeters;
            lines.push_back({first, second, minorColor});

            first = {};
            second = {};
            first[face.axis] = second[face.axis] = face.sign * halfExtentMeters;
            first[axisV] = second[axisV] = offset;
            first[axisU] = -halfExtentMeters;
            second[axisU] = halfExtentMeters;
            lines.push_back({first, second, minorColor});
        }
        const float marker = std::min(0.30F, halfExtentMeters * 0.15F);
        glm::vec3 first{};
        glm::vec3 second{};
        first[face.axis] = second[face.axis] = face.sign * halfExtentMeters;
        first[axisU] = -marker;
        second[axisU] = marker;
        lines.push_back({first, second, face.color});
        first = {};
        second = {};
        first[face.axis] = second[face.axis] = face.sign * halfExtentMeters;
        first[axisV] = -marker;
        second[axisV] = marker;
        lines.push_back({first, second, face.color});
    }
    lines.push_back({{-halfExtentMeters, 0, 0}, {halfExtentMeters, 0, 0},
                     {1.0F, 0.18F, 0.12F}});
    lines.push_back({{0, -halfExtentMeters, 0}, {0, halfExtentMeters, 0},
                     {0.20F, 1.0F, 0.24F}});
    lines.push_back({{0, 0, -halfExtentMeters}, {0, 0, halfExtentMeters},
                     {0.35F, 0.62F, 1.0F}});
    return lines;
}

}  // namespace nadoc_vr
