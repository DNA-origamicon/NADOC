#pragma once
#include <algorithm>
#include <cmath>
#include <utility>
#include <glm/glm.hpp>

namespace nadoc_vr {
// Keep schematic Full bars on their actual slabs, including independent MD
// rotations. Ordinary base translations alone cannot transport an off-centre site.
template<class Source, class Index, class Frames, class Cylinder>
auto cpdVisualizationOffsets(const Source& source, const Index& index,
                            const Frames& frames, const Cylinder& cylinder,
                            glm::vec3 center, float scale, float distance,
                            std::pair<glm::vec3, glm::vec3> offsets) {
    if (!cylinder.identity.starts_with("cpd:") || frames.empty()) return offsets;
    const auto owners = index.ownership.find(cylinder.identity);
    if (owners == index.ownership.end()) return offsets;
    for (const auto& owner : owners->second->owners) {
        const auto live = frames.find(owner.token);
        if (live == frames.end()) continue;
        for (const auto& box : source.boxes) {
            const auto aliases = index.aliases.find(box.identity);
            if (aliases == index.aliases.end() ||
                std::find(aliases->second->tokens.begin(), aliases->second->tokens.end(),
                          owner.token) == aliases->second->tokens.end()) continue;
            const glm::mat3 axes(box.axisX, box.axisY, box.axisZ);
            if (std::abs(glm::determinant(axes)) < 1e-12F) continue;
            const auto& frame = live->second;
            const auto targetCenter = (frame.slabCenter-center)*scale-glm::vec3(0,0,distance);
            const glm::mat3 targetAxes(frame.slabAxisX*scale, frame.slabAxisY*scale, frame.slabAxisZ*scale);
            auto delta = [&](glm::vec3 point) {
                return targetCenter + targetAxes * (glm::inverse(axes)*(point-box.center)) - point;
            };
            if (owner.startWeight > 0) offsets.first = delta(cylinder.start);
            if (owner.endWeight > 0) offsets.second = delta(cylinder.end);
            break;
        }
    }
    return offsets;
}
}
