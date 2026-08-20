#pragma once

#include <charconv>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

#include <glm/glm.hpp>

namespace nadoc_vr {

struct VisualizationPoint {
    std::string ownerToken;
    glm::vec3 position{};
    bool hasColor = false;
    glm::vec3 color{};
};

struct VisualizationSnapshot {
    uint64_t sequence = 0;
    std::string mode = "none";
    std::vector<VisualizationPoint> points;
};

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
    std::string countToken;
    std::string extra;
    if (!(headerStream >> magic >> versionToken >> sequenceToken >> mode >> countToken) ||
        headerStream >> extra || magic != "NADOCVR_VISUALIZATION" ||
        strictVisualizationUnsigned(versionToken, 1, 1) != 1 ||
        !validVisualizationMode(mode)) {
        throw std::runtime_error("invalid VR visualization header");
    }
    const uint64_t sequence = strictVisualizationUnsigned(
        sequenceToken, 1, 9'007'199'254'740'991ULL);
    const size_t count = static_cast<size_t>(strictVisualizationUnsigned(
        countToken, 0, 200'000));

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
                  >> point.position.z >> color) || row >> extra || record != "V" ||
            point.ownerToken.empty() || point.ownerToken.size() > 2048 ||
            !ownerTokens.insert(point.ownerToken).second ||
            !std::isfinite(point.position.x) || !std::isfinite(point.position.y) ||
            !std::isfinite(point.position.z)) {
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
    return {sequence, std::move(mode), std::move(points)};
}

}  // namespace nadoc_vr
