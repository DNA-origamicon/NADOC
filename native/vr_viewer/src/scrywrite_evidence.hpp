#pragma once

#include "scrywrite_witness.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <iomanip>
#include <istream>
#include <limits>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace nadoc_vr::scrywrite {

struct EvidencePoint {
    std::string identity;
    glm::vec3 position{};
    float radius = 0.01F;
    glm::vec3 color{0.8F};
};

struct EvidenceSegment {
    std::string identity;
    glm::vec3 start{};
    glm::vec3 end{};
    float radius = 0.01F;
    glm::vec3 color{0.8F};
};

struct EvidenceScene {
    std::vector<EvidencePoint> points;
    std::vector<EvidenceSegment> segments;
    glm::vec3 center{};
    float scale = 1.0F;
};

struct EvidenceBundle {
    std::string povSvg;
    std::string topDownSvg;
    std::string metricsJson;
    size_t totalPrimitives = 0;
    size_t inFrontPrimitives = 0;
    size_t inFramePrimitives = 0;
    size_t fullyInFramePrimitives = 0;
    size_t clippedPrimitives = 0;
    size_t readablePrimitives = 0;
    float projectedBoundsFraction = 0.0F;
    bool validationEvaluated = false;
    bool validationPassed = false;
    std::vector<std::string> validationFailures;
    float headsetYawDegrees = 0.0F;
    float headsetPitchDegrees = 0.0F;
    float origamiYawDegrees = 0.0F;
    float relativeYawDegrees = 0.0F;
    float gazeTargetErrorDegrees = 0.0F;
    float targetDistanceMeters = 0.0F;
};

struct EvidenceExpectations {
    size_t totalPrimitives = 0;
    float minInFrameFraction = 0.0F;
    float minFullyInFrameFraction = 0.0F;
    size_t maxClippedPrimitives = 0;
    float minReadableFraction = 0.0F;
    float minProjectedBoundsFraction = 0.0F;
    float maxGazeErrorDegrees = 0.0F;
};

inline float evidenceNumber(const std::string& token, size_t line);

inline EvidenceExpectations loadEvidenceExpectations(std::istream& input) {
    EvidenceExpectations result;
    std::set<std::string> seen;
    std::string lineText;
    size_t line = 0;
    bool header = false;
    auto fail = [](size_t lineNumber, const std::string& message) -> void {
        throw std::runtime_error("expectation line " + std::to_string(lineNumber) +
                                 ": " + message);
    };
    auto fraction = [&](const std::string& token) {
        const float value = evidenceNumber(token, line);
        if (value < 0.0F || value > 1.0F) fail(line, "fraction must be between 0 and 1");
        return value;
    };
    auto count = [&](const std::string& token) {
        size_t consumed = 0;
        unsigned long long value = 0;
        try {
            value = std::stoull(token, &consumed);
        } catch (const std::exception&) {
            fail(line, "invalid non-negative integer: " + token);
        }
        if (consumed != token.size() || value > 1'000'000ULL) {
            fail(line, "invalid non-negative integer: " + token);
        }
        return static_cast<size_t>(value);
    };
    while (std::getline(input, lineText)) {
        ++line;
        if (!lineText.empty() && lineText.back() == '\r') lineText.pop_back();
        std::istringstream parser(lineText);
        std::vector<std::string> fields;
        std::string field;
        while (parser >> field) fields.push_back(field);
        if (fields.empty() || fields.front().starts_with('#')) continue;
        if (!header) {
            if (fields.size() != 2 || fields[0] != "SCRYWRITE_EVIDENCE" ||
                fields[1] != "1") {
                fail(line, "expected SCRYWRITE_EVIDENCE 1 header");
            }
            header = true;
            continue;
        }
        if (fields.size() != 2) fail(line, "expected <metric> <value>");
        if (!seen.insert(fields[0]).second) fail(line, "duplicate metric " + fields[0]);
        if (fields[0] == "total_primitives") result.totalPrimitives = count(fields[1]);
        else if (fields[0] == "min_in_frame_fraction") {
            result.minInFrameFraction = fraction(fields[1]);
        } else if (fields[0] == "min_fully_in_frame_fraction") {
            result.minFullyInFrameFraction = fraction(fields[1]);
        } else if (fields[0] == "max_clipped_primitives") {
            result.maxClippedPrimitives = count(fields[1]);
        } else if (fields[0] == "min_readable_fraction") {
            result.minReadableFraction = fraction(fields[1]);
        } else if (fields[0] == "min_projected_bounds_fraction") {
            result.minProjectedBoundsFraction = fraction(fields[1]);
        } else if (fields[0] == "max_gaze_error_degrees") {
            result.maxGazeErrorDegrees = evidenceNumber(fields[1], line);
            if (result.maxGazeErrorDegrees < 0.0F || result.maxGazeErrorDegrees > 180.0F) {
                fail(line, "gaze error must be between 0 and 180 degrees");
            }
        } else {
            fail(line, "unknown metric " + fields[0]);
        }
    }
    static const std::array<const char*, 7> required = {
        "total_primitives", "min_in_frame_fraction", "min_fully_in_frame_fraction",
        "max_clipped_primitives", "min_readable_fraction",
        "min_projected_bounds_fraction", "max_gaze_error_degrees",
    };
    if (!header) fail(1, "missing SCRYWRITE_EVIDENCE 1 header");
    for (const char* name : required) {
        if (!seen.contains(name)) fail(line == 0 ? 1 : line, std::string("missing metric ") + name);
    }
    return result;
}

inline float evidenceNumber(const std::string& token, size_t line) {
    size_t consumed = 0;
    double value = 0.0;
    try {
        value = std::stod(token, &consumed);
    } catch (const std::exception&) {
        throw std::runtime_error("scene line " + std::to_string(line) +
                                 ": invalid number " + token);
    }
    if (consumed != token.size() || !std::isfinite(value) ||
        std::abs(value) > std::numeric_limits<float>::max()) {
        throw std::runtime_error("scene line " + std::to_string(line) +
                                 ": invalid number " + token);
    }
    return static_cast<float>(value);
}

inline EvidenceScene loadEvidenceScene(std::istream& input) {
    EvidenceScene scene;
    std::string lineText;
    size_t line = 0;
    bool header = false;
    bool activeFull = false;
    while (std::getline(input, lineText)) {
        ++line;
        if (!lineText.empty() && lineText.back() == '\r') lineText.pop_back();
        std::istringstream parser(lineText);
        std::vector<std::string> fields;
        std::string field;
        while (parser >> field) fields.push_back(field);
        if (fields.empty() || fields.front().starts_with('#')) continue;
        if (!header) {
            if (fields.size() != 4 || fields[0] != "NADOCVR") {
                throw std::runtime_error("scene line 1: expected NADOCVR header");
            }
            header = true;
            continue;
        }
        if (fields[0] == "R") {
            if (fields.size() != 2) {
                throw std::runtime_error("scene line " + std::to_string(line) +
                                         ": malformed representation");
            }
            activeFull = fields[1] == "full" && scene.points.empty() &&
                         scene.segments.empty();
            continue;
        }
        if (fields[0] == "E") {
            activeFull = false;
            continue;
        }
        if (!activeFull) continue;
        if (fields[0] == "P") {
            if (fields.size() < 9) {
                throw std::runtime_error("scene line " + std::to_string(line) +
                                         ": malformed point");
            }
            scene.points.push_back({
                fields[1],
                {evidenceNumber(fields[2], line), evidenceNumber(fields[3], line),
                 evidenceNumber(fields[4], line)},
                evidenceNumber(fields[5], line),
                {evidenceNumber(fields[6], line), evidenceNumber(fields[7], line),
                 evidenceNumber(fields[8], line)},
            });
        } else if (fields[0] == "C" || fields[0] == "H") {
            if (fields.size() < 12) {
                throw std::runtime_error("scene line " + std::to_string(line) +
                                         ": malformed cylinder");
            }
            scene.segments.push_back({
                fields[1],
                {evidenceNumber(fields[2], line), evidenceNumber(fields[3], line),
                 evidenceNumber(fields[4], line)},
                {evidenceNumber(fields[5], line), evidenceNumber(fields[6], line),
                 evidenceNumber(fields[7], line)},
                evidenceNumber(fields[8], line),
                {evidenceNumber(fields[9], line), evidenceNumber(fields[10], line),
                 evidenceNumber(fields[11], line)},
            });
        }
    }
    if (!header || (scene.points.empty() && scene.segments.empty())) {
        throw std::runtime_error("scene contains no natural Full geometry");
    }
    glm::vec3 lo(std::numeric_limits<float>::max());
    glm::vec3 hi(std::numeric_limits<float>::lowest());
    auto include = [&](const glm::vec3& value) {
        lo = glm::min(lo, value);
        hi = glm::max(hi, value);
    };
    for (const auto& point : scene.points) include(point.position);
    for (const auto& segment : scene.segments) {
        include(segment.start);
        include(segment.end);
    }
    scene.center = (lo + hi) * 0.5F;
    const glm::vec3 extent = hi - lo;
    scene.scale = 0.60F / std::max({extent.x, extent.y, extent.z, 1.0e-6F});
    auto normalized = [&](const glm::vec3& value) {
        glm::vec3 result = (value - scene.center) * scene.scale;
        result.z -= 1.30F;
        return result;
    };
    for (auto& point : scene.points) {
        point.position = normalized(point.position);
        point.radius *= scene.scale;
    }
    for (auto& segment : scene.segments) {
        segment.start = normalized(segment.start);
        segment.end = normalized(segment.end);
        segment.radius *= scene.scale;
    }
    return scene;
}

inline std::string evidenceColor(const glm::vec3& color) {
    auto channel = [](float value) {
        return static_cast<int>(std::round(glm::clamp(value, 0.0F, 1.0F) * 255.0F));
    };
    return "rgb(" + std::to_string(channel(color.r)) + "," +
           std::to_string(channel(color.g)) + "," +
           std::to_string(channel(color.b)) + ")";
}

inline std::string evidenceXml(const std::string& value) {
    std::string output;
    for (char character : value) {
        if (character == '&') output += "&amp;";
        else if (character == '<') output += "&lt;";
        else if (character == '>') output += "&gt;";
        else if (character == '\"') output += "&quot;";
        else output += character;
    }
    return output;
}

inline std::string evidenceJson(const std::string& value) {
    std::ostringstream output;
    for (const unsigned char character : value) {
        switch (character) {
            case '"': output << "\\\""; break;
            case '\\': output << "\\\\"; break;
            case '\b': output << "\\b"; break;
            case '\f': output << "\\f"; break;
            case '\n': output << "\\n"; break;
            case '\r': output << "\\r"; break;
            case '\t': output << "\\t"; break;
            default:
                if (character < 0x20U) {
                    output << "\\u" << std::hex << std::setw(4)
                           << std::setfill('0') << static_cast<int>(character)
                           << std::dec << std::setfill(' ');
                } else {
                    output << static_cast<char>(character);
                }
        }
    }
    return output.str();
}

inline std::vector<glm::vec3> evidencePositions(const EvidenceScene& scene) {
    std::vector<glm::vec3> positions;
    positions.reserve(scene.points.size() + scene.segments.size() * 2U);
    for (const auto& point : scene.points) positions.push_back(point.position);
    for (const auto& segment : scene.segments) {
        positions.push_back(segment.start);
        positions.push_back(segment.end);
    }
    return positions;
}

inline float evidenceOrigamiYaw(const EvidenceScene& scene) {
    const auto positions = evidencePositions(scene);
    glm::vec2 center{};
    for (const auto& position : positions) center += glm::vec2(position.x, position.z);
    center /= static_cast<float>(positions.size());
    float xx = 0.0F;
    float zz = 0.0F;
    float xz = 0.0F;
    for (const auto& position : positions) {
        const glm::vec2 offset(position.x - center.x, position.z - center.y);
        xx += offset.x * offset.x;
        zz += offset.y * offset.y;
        xz += offset.x * offset.y;
    }
    const float axisFromX = 0.5F * std::atan2(2.0F * xz, xx - zz);
    const glm::vec2 axis(std::cos(axisFromX), std::sin(axisFromX));
    return glm::degrees(std::atan2(axis.x, -axis.y));
}

inline EvidenceBundle renderEvidence(
    const EvidenceScene& scene, const WitnessInput& actor,
    const std::string& sceneLabel,
    const EvidenceExpectations* expectations = nullptr) {
    constexpr float pi = 3.14159265358979323846F;
    constexpr float verticalFov = 72.0F * pi / 180.0F;
    constexpr float width = 1280.0F;
    constexpr float height = 720.0F;
    const float focalY = height * 0.5F / std::tan(verticalFov * 0.5F);
    const float focalX = focalY;
    const glm::quat inverseHead = glm::inverse(actor.head.orientation);
    auto camera = [&](const glm::vec3& world) {
        return inverseHead * (world - actor.head.position);
    };
    auto project = [&](const glm::vec3& world) -> std::optional<glm::vec3> {
        const glm::vec3 local = camera(world);
        const float depth = -local.z;
        if (depth <= 0.02F) return std::nullopt;
        const float x = width * 0.5F + local.x * focalX / depth;
        const float y = height * 0.5F - local.y * focalY / depth;
        return glm::vec3(x, y, depth);
    };

    auto lineIntersects = [&](glm::vec2 first, glm::vec2 second, float padding) {
        const glm::vec2 delta = second - first;
        float lower = 0.0F;
        float upper = 1.0F;
        auto clip = [&](float p, float q) {
            if (std::abs(p) < 1.0e-7F) return q >= 0.0F;
            const float ratio = q / p;
            if (p < 0.0F) {
                if (ratio > upper) return false;
                lower = std::max(lower, ratio);
            } else {
                if (ratio < lower) return false;
                upper = std::min(upper, ratio);
            }
            return true;
        };
        return clip(-delta.x, first.x + padding) &&
               clip(delta.x, width + padding - first.x) &&
               clip(-delta.y, first.y + padding) &&
               clip(delta.y, height + padding - first.y);
    };
    auto contained = [&](const glm::vec2& point, float padding) {
        return point.x >= padding && point.x <= width - padding &&
               point.y >= padding && point.y <= height - padding;
    };

    struct DrawSegment {
        glm::vec3 first{};
        glm::vec3 second{};
        float radius = 1.0F;
        glm::vec3 color{};
        float depth = 0.0F;
        float stroke = 1.0F;
    };
    struct DrawPoint {
        EvidencePoint point;
        glm::vec3 projected{};
        float radius = 1.0F;
    };
    EvidenceBundle result;
    result.totalPrimitives = scene.segments.size() + scene.points.size();
    glm::vec2 projectedLo(width, height);
    glm::vec2 projectedHi(0.0F, 0.0F);
    bool hasProjectedBounds = false;
    auto includeProjectedBounds = [&](float x0, float y0, float x1, float y1) {
        projectedLo = glm::min(projectedLo, glm::vec2(
            glm::clamp(x0, 0.0F, width), glm::clamp(y0, 0.0F, height)));
        projectedHi = glm::max(projectedHi, glm::vec2(
            glm::clamp(x1, 0.0F, width), glm::clamp(y1, 0.0F, height)));
        hasProjectedBounds = true;
    };
    std::vector<DrawSegment> inFrameSegments;
    for (const auto& segment : scene.segments) {
        const auto first = project(segment.start);
        const auto second = project(segment.end);
        if (!first || !second) continue;
        ++result.inFrontPrimitives;
        const float depth = (first->z + second->z) * 0.5F;
        const float stroke = segment.radius * focalY * 2.0F / depth;
        const float padding = stroke * 0.5F;
        const glm::vec2 a(first->x, first->y);
        const glm::vec2 b(second->x, second->y);
        if (!lineIntersects(a, b, padding)) continue;
        ++result.inFramePrimitives;
        const bool fullyContained = contained(a, padding) && contained(b, padding);
        if (fullyContained) ++result.fullyInFramePrimitives;
        else ++result.clippedPrimitives;
        if (stroke >= 1.0F && glm::length(b - a) >= 3.0F) {
            ++result.readablePrimitives;
        }
        includeProjectedBounds(
            std::min(a.x, b.x) - padding, std::min(a.y, b.y) - padding,
            std::max(a.x, b.x) + padding, std::max(a.y, b.y) + padding);
        inFrameSegments.push_back({*first, *second, segment.radius, segment.color,
                                   depth, stroke});
    }
    std::sort(inFrameSegments.begin(), inFrameSegments.end(),
              [](const auto& first, const auto& second) {
                  return first.depth > second.depth;
              });
    std::vector<DrawPoint> inFramePoints;
    for (const auto& point : scene.points) {
        if (const auto projected = project(point.position)) {
            ++result.inFrontPrimitives;
            const float radius = point.radius * focalY / projected->z;
            const glm::vec2 center(projected->x, projected->y);
            if (center.x + radius < 0.0F || center.x - radius > width ||
                center.y + radius < 0.0F || center.y - radius > height) continue;
            ++result.inFramePrimitives;
            if (contained(center, radius)) ++result.fullyInFramePrimitives;
            else ++result.clippedPrimitives;
            if (radius * 2.0F >= 3.0F) ++result.readablePrimitives;
            includeProjectedBounds(center.x - radius, center.y - radius,
                                   center.x + radius, center.y + radius);
            inFramePoints.push_back({point, *projected, radius});
        }
    }
    if (hasProjectedBounds) {
        const glm::vec2 extent = glm::max(projectedHi - projectedLo, glm::vec2(0.0F));
        result.projectedBoundsFraction = extent.x * extent.y / (width * height);
    }
    const glm::vec3 headForward = actor.head.orientation * glm::vec3(0.0F, 0.0F, -1.0F);
    result.headsetYawDegrees = glm::degrees(std::atan2(headForward.x, -headForward.z));
    result.headsetPitchDegrees = glm::degrees(
        std::asin(glm::clamp(headForward.y, -1.0F, 1.0F)));
    result.origamiYawDegrees = evidenceOrigamiYaw(scene);
    result.relativeYawDegrees = result.origamiYawDegrees - result.headsetYawDegrees;
    while (result.relativeYawDegrees > 90.0F) result.relativeYawDegrees -= 180.0F;
    while (result.relativeYawDegrees < -90.0F) result.relativeYawDegrees += 180.0F;
    const auto positions = evidencePositions(scene);
    glm::vec3 targetLo(std::numeric_limits<float>::max());
    glm::vec3 targetHi(std::numeric_limits<float>::lowest());
    for (const auto& position : positions) {
        targetLo = glm::min(targetLo, position);
        targetHi = glm::max(targetHi, position);
    }
    const glm::vec3 targetOffset = (targetLo + targetHi) * 0.5F - actor.head.position;
    result.targetDistanceMeters = glm::length(targetOffset);
    if (result.targetDistanceMeters > 1.0e-6F) {
        result.gazeTargetErrorDegrees = glm::degrees(std::acos(glm::clamp(
            glm::dot(glm::normalize(headForward), glm::normalize(targetOffset)),
            -1.0F, 1.0F)));
    }

    if (expectations) {
        result.validationEvaluated = true;
        const float denominator = static_cast<float>(std::max<size_t>(1, result.totalPrimitives));
        const float inFrameFraction = static_cast<float>(result.inFramePrimitives) / denominator;
        const float fullyInFrameFraction =
            static_cast<float>(result.fullyInFramePrimitives) / denominator;
        const float readableFraction =
            static_cast<float>(result.readablePrimitives) / denominator;
        auto require = [&](bool condition, const std::string& message) {
            if (!condition) result.validationFailures.push_back(message);
        };
        require(result.totalPrimitives == expectations->totalPrimitives,
                "total_primitives expected " +
                    std::to_string(expectations->totalPrimitives) + ", got " +
                    std::to_string(result.totalPrimitives));
        require(inFrameFraction >= expectations->minInFrameFraction,
                "in_frame_fraction below minimum");
        require(fullyInFrameFraction >= expectations->minFullyInFrameFraction,
                "fully_in_frame_fraction below minimum");
        require(result.clippedPrimitives <= expectations->maxClippedPrimitives,
                "clipped_primitives above maximum");
        require(readableFraction >= expectations->minReadableFraction,
                "readable_fraction below minimum");
        require(result.projectedBoundsFraction >=
                    expectations->minProjectedBoundsFraction,
                "projected_bounds_fraction below minimum");
        require(result.gazeTargetErrorDegrees <= expectations->maxGazeErrorDegrees,
                "gaze_to_target_error_degrees above maximum");
        result.validationPassed = result.validationFailures.empty();
    }

    std::ostringstream pov;
    pov << std::fixed << std::setprecision(3)
        << "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1280\" height=\"720\" "
           "viewBox=\"0 0 1280 720\">\n"
        << "<rect width=\"1280\" height=\"720\" fill=\"#07101d\"/>\n"
        << "<text x=\"32\" y=\"46\" fill=\"#dcf7ff\" font-family=\"monospace\" "
           "font-size=\"24\">SCRYWRITE ACTOR POV</text>\n"
        << "<text x=\"32\" y=\"76\" fill=\"#74d9f5\" font-family=\"monospace\" "
           "font-size=\"16\">" << evidenceXml(sceneLabel) << " | FOV 72 DEG | "
        << result.inFramePrimitives << "/" << result.totalPrimitives
        << " PRIMITIVES IN FRAME</text>\n";
    for (const auto& segment : inFrameSegments) {
        const float stroke = glm::clamp(
            segment.stroke, 2.0F, 22.0F);
        pov << "<line x1=\"" << segment.first.x << "\" y1=\"" << segment.first.y
            << "\" x2=\"" << segment.second.x << "\" y2=\"" << segment.second.y
            << "\" stroke=\"" << evidenceColor(segment.color)
            << "\" stroke-width=\"" << stroke
            << "\" stroke-linecap=\"round\"/>\n";
    }
    for (const auto& draw : inFramePoints) {
        const float radius = glm::clamp(draw.radius, 3.0F, 18.0F);
        pov << "<circle cx=\"" << draw.projected.x << "\" cy=\"" << draw.projected.y
            << "\" r=\"" << radius << "\" fill=\"" << evidenceColor(draw.point.color)
            << "\" stroke=\"#ffffff\" stroke-width=\"1.5\"/>\n";
    }
    pov << "<path d=\"M620 360h40 M640 340v40\" stroke=\"#42f5d7\" "
           "stroke-width=\"2\" opacity=\"0.8\"/>\n"
        << "<rect x=\"18\" y=\"18\" width=\"1244\" height=\"684\" rx=\"18\" "
           "fill=\"none\" stroke=\"#1a6074\" stroke-width=\"2\"/>\n"
        << "<text x=\"32\" y=\"684\" fill=\"#8da8b7\" font-family=\"monospace\" "
           "font-size=\"15\">SCRIPTED ACTOR FORWARD = [" << headForward.x << ", "
        << headForward.y << ", " << headForward.z << "] | TARGET ERROR "
        << result.gazeTargetErrorDegrees << " DEG</text>\n</svg>\n";
    result.povSvg = pov.str();

    glm::vec2 sceneCenter{};
    for (const auto& position : positions) {
        sceneCenter += glm::vec2(position.x, position.z);
    }
    sceneCenter /= static_cast<float>(positions.size());
    const float axisRadians = glm::radians(result.origamiYawDegrees);
    const glm::vec2 longAxis(std::sin(axisRadians), -std::cos(axisRadians));
    const glm::vec2 shortAxis(-longAxis.y, longAxis.x);
    float minLong = std::numeric_limits<float>::max();
    float maxLong = std::numeric_limits<float>::lowest();
    float minShort = minLong;
    float maxShort = maxLong;
    for (const auto& position : positions) {
        const glm::vec2 offset(position.x - sceneCenter.x, position.z - sceneCenter.y);
        minLong = std::min(minLong, glm::dot(offset, longAxis));
        maxLong = std::max(maxLong, glm::dot(offset, longAxis));
        minShort = std::min(minShort, glm::dot(offset, shortAxis));
        maxShort = std::max(maxShort, glm::dot(offset, shortAxis));
    }
    const glm::vec3 forward3 = actor.head.orientation * glm::vec3(0.0F, 0.0F, -1.0F);
    const glm::vec2 headForward2 = glm::length(glm::vec2(forward3.x, forward3.z)) > 1.0e-6F
        ? glm::normalize(glm::vec2(forward3.x, forward3.z)) : glm::vec2(0.0F, -1.0F);
    glm::vec2 lo(-0.7F, -1.75F);
    glm::vec2 hi(0.7F, 0.25F);
    auto map = [&](const glm::vec2& world) {
        constexpr float margin = 90.0F;
        return glm::vec2(
            margin + (world.x - lo.x) / (hi.x - lo.x) * (1000.0F - 2.0F * margin),
            margin + (world.y - lo.y) / (hi.y - lo.y) * (800.0F - 2.0F * margin));
    };
    auto world2 = [](const glm::vec3& value) { return glm::vec2(value.x, value.z); };
    std::ostringstream top;
    top << std::fixed << std::setprecision(3)
        << "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1000\" height=\"800\" "
           "viewBox=\"0 0 1000 800\">\n"
        << "<rect width=\"1000\" height=\"800\" fill=\"#09131d\"/>\n"
        << "<text x=\"30\" y=\"42\" fill=\"#dcf7ff\" font-family=\"monospace\" "
           "font-size=\"24\">SCRYWRITE TOP-DOWN ORIENTATION</text>\n";
    for (float x = -0.5F; x <= 0.5F; x += 0.25F) {
        const glm::vec2 a = map({x, lo.y});
        const glm::vec2 b = map({x, hi.y});
        top << "<line x1=\"" << a.x << "\" y1=\"" << a.y << "\" x2=\""
            << b.x << "\" y2=\"" << b.y
            << "\" stroke=\"#163041\" stroke-width=\"1\"/>\n";
    }
    for (float z = -1.75F; z <= 0.25F; z += 0.25F) {
        const glm::vec2 a = map({lo.x, z});
        const glm::vec2 b = map({hi.x, z});
        top << "<line x1=\"" << a.x << "\" y1=\"" << a.y << "\" x2=\""
            << b.x << "\" y2=\"" << b.y
            << "\" stroke=\"#163041\" stroke-width=\"1\"/>\n";
    }
    for (const auto& segment : scene.segments) {
        const glm::vec2 first = map(world2(segment.start));
        const glm::vec2 second = map(world2(segment.end));
        top << "<line x1=\"" << first.x << "\" y1=\"" << first.y
            << "\" x2=\"" << second.x << "\" y2=\"" << second.y
            << "\" stroke=\"" << evidenceColor(segment.color)
            << "\" stroke-width=\"5\" stroke-linecap=\"round\"/>\n";
    }
    for (const auto& point : scene.points) {
        const glm::vec2 projected = map(world2(point.position));
        top << "<circle cx=\"" << projected.x << "\" cy=\"" << projected.y
            << "\" r=\"8\" fill=\"" << evidenceColor(point.color)
            << "\" stroke=\"#ffffff\" stroke-width=\"2\"/>\n";
    }
    std::array<glm::vec2, 4> bounds = {
        sceneCenter + longAxis * minLong + shortAxis * minShort,
        sceneCenter + longAxis * maxLong + shortAxis * minShort,
        sceneCenter + longAxis * maxLong + shortAxis * maxShort,
        sceneCenter + longAxis * minLong + shortAxis * maxShort,
    };
    top << "<polygon points=\"";
    for (const auto& corner : bounds) {
        const glm::vec2 point = map(corner);
        top << point.x << ',' << point.y << ' ';
    }
    top << "\" fill=\"none\" stroke=\"#ffe36e\" stroke-width=\"3\" "
           "stroke-dasharray=\"10 7\"/>\n";
    const glm::vec2 head = map(world2(actor.head.position));
    const glm::vec2 headTip = map(world2(actor.head.position) + headForward2 * 0.28F);
    top << "<circle cx=\"" << head.x << "\" cy=\"" << head.y
        << "\" r=\"15\" fill=\"#1fe0ff\" stroke=\"#ffffff\" stroke-width=\"3\"/>\n"
        << "<line x1=\"" << head.x << "\" y1=\"" << head.y << "\" x2=\""
        << headTip.x << "\" y2=\"" << headTip.y
        << "\" stroke=\"#1fe0ff\" stroke-width=\"7\" marker-end=\"url(#arrow)\"/>\n";
    for (size_t hand = 0; hand < actor.hands.size(); ++hand) {
        if (!actor.hands[hand].valid) continue;
        const glm::vec2 point = map(world2(actor.hands[hand].position));
        top << "<circle cx=\"" << point.x << "\" cy=\"" << point.y
            << "\" r=\"10\" fill=\"" << (hand == 0 ? "#33bfff" : "#ff8b2c")
            << "\" stroke=\"#ffffff\" stroke-width=\"2\"/>\n";
    }
    top << "<defs><marker id=\"arrow\" markerWidth=\"10\" markerHeight=\"10\" "
           "refX=\"8\" refY=\"3\" orient=\"auto\"><path d=\"M0,0 L0,6 L9,3 z\" "
           "fill=\"#1fe0ff\"/></marker></defs>\n"
        << "<text x=\"30\" y=\"748\" fill=\"#1fe0ff\" font-family=\"monospace\" "
           "font-size=\"17\">SCRIPTED ACTOR YAW " << result.headsetYawDegrees
        << " / PITCH " << result.headsetPitchDegrees << " DEG</text>\n"
        << "<text x=\"500\" y=\"748\" fill=\"#ffe36e\" font-family=\"monospace\" "
           "font-size=\"17\">STRUCTURE LONG AXIS YAW " << result.origamiYawDegrees
        << " DEG</text>\n"
        << "<text x=\"30\" y=\"775\" fill=\"#8da8b7\" font-family=\"monospace\" "
           "font-size=\"14\">TOP DOWN: X HORIZONTAL, FORWARD -Z TOWARD TOP</text>\n"
        << "<text x=\"600\" y=\"775\" fill=\"#ffe36e\" font-family=\"monospace\" "
           "font-size=\"14\">RELATIVE AXIS YAW " << result.relativeYawDegrees
        << " DEG</text>\n"
        << "</svg>\n";
    result.topDownSvg = top.str();

    std::ostringstream metrics;
    const float denominator = static_cast<float>(std::max<size_t>(1, result.totalPrimitives));
    metrics << std::fixed << std::setprecision(6)
            << "{\n  \"schema\": \"scrywrite.evidence.v2\",\n"
            << "  \"scene\": \"" << evidenceJson(sceneLabel) << "\",\n"
            << "  \"geometry\": {\"points\": " << scene.points.size()
            << ", \"segments\": " << scene.segments.size()
            << ", \"total_primitives\": " << result.totalPrimitives
            << ", \"in_front_primitives\": " << result.inFrontPrimitives
            << ", \"in_frame_primitives\": " << result.inFramePrimitives
            << ", \"fully_in_frame_primitives\": " << result.fullyInFramePrimitives
            << ", \"clipped_primitives\": " << result.clippedPrimitives
            << ", \"readable_primitives\": " << result.readablePrimitives
            << ", \"in_frame_fraction\": "
            << static_cast<float>(result.inFramePrimitives) / denominator
            << ", \"fully_in_frame_fraction\": "
            << static_cast<float>(result.fullyInFramePrimitives) / denominator
            << ", \"readable_fraction\": "
            << static_cast<float>(result.readablePrimitives) / denominator
            << ", \"projected_bounds_fraction\": "
            << result.projectedBoundsFraction << "},\n"
            << "  \"scripted_actor_yaw_degrees\": " << result.headsetYawDegrees << ",\n"
            << "  \"scripted_actor_pitch_degrees\": " << result.headsetPitchDegrees << ",\n"
            << "  \"structure_long_axis_yaw_degrees\": " << result.origamiYawDegrees << ",\n"
            << "  \"relative_axis_yaw_degrees\": " << result.relativeYawDegrees << ",\n"
            << "  \"gaze_to_target_error_degrees\": "
            << result.gazeTargetErrorDegrees << ",\n"
            << "  \"target_distance_meters\": " << result.targetDistanceMeters << ",\n"
            << "  \"validation\": {\"status\": \""
            << (!result.validationEvaluated ? "not_evaluated"
                                            : result.validationPassed ? "passed" : "failed")
            << "\", \"failures\": [";
    for (size_t index = 0; index < result.validationFailures.size(); ++index) {
        if (index > 0) metrics << ", ";
        metrics << "\"" << evidenceJson(result.validationFailures[index]) << "\"";
    }
    metrics << "]}\n}\n";
    result.metricsJson = metrics.str();
    return result;
}

}  // namespace nadoc_vr::scrywrite
