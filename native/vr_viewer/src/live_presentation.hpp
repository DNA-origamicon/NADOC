#pragma once
#include <iomanip>
#include <limits>
#include <sstream>
#include <string>
#include <glm/glm.hpp>

namespace nadoc_vr {
// Read-only observation: source nanometers -> normalized model -> tracking meters.
inline std::string livePresentationJson(const glm::mat4& modelToTracking,
    const glm::vec3& sourceCenter, float normalizationScale, const glm::vec3& offset) {
    std::ostringstream out;
    out << std::setprecision(std::numeric_limits<float>::max_digits10);
    auto vector = [&](const glm::vec3& p) { out << '[' << p.x << ',' << p.y << ',' << p.z << ']'; };
    out << "{\"model_to_tracking_rows\":[";
    for (int row=0;row<4;++row) {
        if (row) out << ',';
        out << '[';
        for (int column=0;column<4;++column) {
            if (column) out << ',';
            out << modelToTracking[column][row];
        }
        out << ']';
    }
    out << "],\"source_center_nm\":"; vector(sourceCenter);
    out << ",\"normalization_model_per_nm\":" << normalizationScale
        << ",\"normalized_offset_model\":"; vector(offset);
    out << '}';
    return out.str();
}
}
