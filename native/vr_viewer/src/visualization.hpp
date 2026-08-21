#pragma once

#include <charconv>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

#include <glm/glm.hpp>

namespace nadoc_vr {

struct VisualizationPoint {
    std::string ownerToken;
    glm::vec3 position{};
    bool hasColor = false;
    glm::vec3 color{};
    bool hasSlabFrame = false;
    glm::vec3 slabCenter{};
    glm::vec3 slabAxisX{};
    glm::vec3 slabAxisY{};
    glm::vec3 slabAxisZ{};
};

struct VisualizationSnapshot {
    uint64_t sequence = 0;
    std::string mode = "none";
    // Version 3 carries style with the displaced geometry so native never applies
    // atom owner mappings to a Full source (or vice versa) between feed polls.
    std::string representation;
    std::string coloring;
    std::vector<VisualizationPoint> points;
};

struct VisualizationOffsetContribution {
    glm::vec3 delta{};
    float startWeight = 0.0F;
    float endWeight = 0.0F;
    bool atomSpecific = false;
};

/** Combine live owner deltas for one primitive. Atomistic primitives also carry
 * Base/Domain aliases for selection, but their measured Atom owner is the exact
 * endpoint coordinate. Once one is present it must replace, rather than add to,
 * the coarser Base displacement. */
inline std::pair<glm::vec3, glm::vec3> aggregateVisualizationOffsets(
    const VisualizationOffsetContribution* contributions, size_t count) {
    bool hasAtomSpecific = false;
    for (size_t index = 0; index < count; ++index) {
        hasAtomSpecific = hasAtomSpecific || contributions[index].atomSpecific;
    }
    glm::vec3 start{};
    glm::vec3 end{};
    for (size_t index = 0; index < count; ++index) {
        const auto& contribution = contributions[index];
        if (hasAtomSpecific && !contribution.atomSpecific) continue;
        start += contribution.delta * contribution.startWeight;
        end += contribution.delta * contribution.endWeight;
    }
    return {start, end};
}

/** Desktop connects a nucleotide bead to the slab's local +X corner and the
 * +/-Z edge facing that bead. The slab axes are full box dimensions. */
inline glm::vec3 visualizationSlabConnectionCorner(
    const glm::vec3& center, const glm::vec3& axisX, const glm::vec3& axisZ,
    const glm::vec3& bead) {
    const float zSign = glm::dot(bead - center, axisZ) < 0.0F ? -1.0F : 1.0F;
    return center + axisX * 0.5F + axisZ * (zSign * 0.5F);
}

inline uint64_t strictVisualizationUnsigned(
    const std::string& token, uint64_t minimum, uint64_t maximum) {
    uint64_t value = 0;
    const auto parsed = std::from_chars(token.data(), token.data() + token.size(), value);
    if (parsed.ec != std::errc{} || parsed.ptr != token.data() + token.size() ||
        value < minimum || value > maximum) {
        throw std::runtime_error("invalid VR visualization integer");
    }
    return value;
}

inline bool validVisualizationMode(const std::string& value) {
    if (value.empty() || value.size() > 32) return false;
    for (const unsigned char character : value) {
        if (!(character >= 'a' && character <= 'z') &&
            !(character >= '0' && character <= '9') &&
            character != '_' && character != '-') {
            return false;
        }
    }
    return true;
}

inline VisualizationSnapshot loadVisualizationSnapshot(const std::string& path) {
    if (path.empty()) return {};
    std::ifstream input(path);
    if (!input) throw std::runtime_error("could not open VR visualization snapshot");

    std::string header;
    if (!std::getline(input, header)) {
        throw std::runtime_error("empty VR visualization snapshot");
    }
    std::istringstream headerStream(header);
    std::string magic;
    std::string versionToken;
    std::string sequenceToken;
    std::string mode;
    std::string representation;
    std::string coloring;
    std::string countToken;
    std::string extra;
    if (!(headerStream >> magic >> versionToken >> sequenceToken >> mode) ||
        magic != "NADOCVR_VISUALIZATION" || !validVisualizationMode(mode)) {
        throw std::runtime_error("invalid VR visualization header");
    }
    const uint64_t version = strictVisualizationUnsigned(versionToken, 1, 3);
    if (version >= 3) {
        if (!(headerStream >> representation >> coloring >> countToken) ||
            (representation != "cylinders" && representation != "full" &&
             representation != "ballstick" && representation != "stick") ||
            (coloring != "strand" && coloring != "base" &&
             coloring != "cluster" && coloring != "cpk")) {
            throw std::runtime_error("invalid VR visualization style");
        }
    } else if (!(headerStream >> countToken)) {
        throw std::runtime_error("invalid VR visualization header");
    }
    if (headerStream >> extra) {
        throw std::runtime_error("invalid VR visualization header");
    }
    const uint64_t sequence = strictVisualizationUnsigned(
        sequenceToken, 1, 9'007'199'254'740'991ULL);
    const size_t count = static_cast<size_t>(strictVisualizationUnsigned(
        countToken, 0, 1'000'000));

    std::vector<VisualizationPoint> points;
    points.reserve(count);
    std::unordered_set<std::string> ownerTokens;
    for (size_t index = 0; index < count; ++index) {
        std::string line;
        if (!std::getline(input, line) || line.size() > 4096) {
            throw std::runtime_error("truncated VR visualization snapshot");
        }
        std::istringstream row(line);
        std::string record;
        VisualizationPoint point;
        std::string color;
        if (!(row >> record >> point.ownerToken >> point.position.x >> point.position.y
                  >> point.position.z >> color) ||
            (record != "V" && record != "F") ||
            (record == "F" && version < 2) ||
            point.ownerToken.empty() || point.ownerToken.size() > 2048 ||
            !ownerTokens.insert(point.ownerToken).second ||
            !std::isfinite(point.position.x) || !std::isfinite(point.position.y) ||
            !std::isfinite(point.position.z)) {
            throw std::runtime_error("invalid VR visualization point");
        }
        if (record == "F") {
            if (!(row >> point.slabCenter.x >> point.slabCenter.y >> point.slabCenter.z
                      >> point.slabAxisX.x >> point.slabAxisX.y >> point.slabAxisX.z
                      >> point.slabAxisY.x >> point.slabAxisY.y >> point.slabAxisY.z
                      >> point.slabAxisZ.x >> point.slabAxisZ.y >> point.slabAxisZ.z) ||
                row >> extra ||
                !std::isfinite(point.slabCenter.x) ||
                !std::isfinite(point.slabCenter.y) ||
                !std::isfinite(point.slabCenter.z) ||
                !std::isfinite(point.slabAxisX.x) ||
                !std::isfinite(point.slabAxisX.y) ||
                !std::isfinite(point.slabAxisX.z) ||
                !std::isfinite(point.slabAxisY.x) ||
                !std::isfinite(point.slabAxisY.y) ||
                !std::isfinite(point.slabAxisY.z) ||
                !std::isfinite(point.slabAxisZ.x) ||
                !std::isfinite(point.slabAxisZ.y) ||
                !std::isfinite(point.slabAxisZ.z)) {
                throw std::runtime_error("invalid VR visualization slab frame");
            }
            point.hasSlabFrame = true;
        } else if (row >> extra) {
            throw std::runtime_error("invalid VR visualization point");
        }
        if (color != "-") {
            if (color.size() != 6) {
                throw std::runtime_error("invalid VR visualization color");
            }
            uint32_t packed = 0;
            const auto parsed = std::from_chars(
                color.data(), color.data() + color.size(), packed, 16);
            if (parsed.ec != std::errc{} || parsed.ptr != color.data() + color.size()) {
                throw std::runtime_error("invalid VR visualization color");
            }
            point.hasColor = true;
            point.color = {
                static_cast<float>((packed >> 16U) & 0xffU) / 255.0F,
                static_cast<float>((packed >> 8U) & 0xffU) / 255.0F,
                static_cast<float>(packed & 0xffU) / 255.0F,
            };
        }
        points.push_back(std::move(point));
    }
    while (std::getline(input, extra)) {
        if (extra.find_first_not_of(" \t\r") != std::string::npos) {
            throw std::runtime_error("unexpected VR visualization data");
        }
    }
    return {
        sequence, std::move(mode), std::move(representation),
        std::move(coloring), std::move(points),
    };
}

}  // namespace nadoc_vr
