#pragma once

#include <glm/glm.hpp>

#include <algorithm>
#include <cmath>
#include <limits>
#include <optional>
#include <string>

namespace nadoc_vr {

struct Ray {
    glm::vec3 origin{};
    glm::vec3 direction{0.0F, 0.0F, -1.0F};
};

struct PickHit {
    std::string identity;
    float distance = std::numeric_limits<float>::max();
    glm::vec3 position{};
};

inline std::optional<float> raySphere(
    const Ray& ray, const glm::vec3& center, float radius) {
    const glm::vec3 offset = ray.origin - center;
    const float along = glm::dot(offset, ray.direction);
    const float constant = glm::dot(offset, offset) - radius * radius;
    const float discriminant = along * along - constant;
    if (discriminant < 0.0F) return std::nullopt;
    const float root = std::sqrt(discriminant);
    const float near = -along - root;
    const float far = -along + root;
    if (near >= 0.0F) return near;
    if (far >= 0.0F) return far;
    return std::nullopt;
}

inline std::optional<float> rayCapsule(
    const Ray& ray, const glm::vec3& start, const glm::vec3& end, float radius) {
    // Inigo Quilez's analytic ray/capsule intersection, plus spherical caps.
    const glm::vec3 axis = end - start;
    const glm::vec3 origin = ray.origin - start;
    const float axisLength2 = glm::dot(axis, axis);
    if (axisLength2 < 1.0e-12F) return raySphere(ray, start, radius);
    const float axisRay = glm::dot(axis, ray.direction);
    const float axisOrigin = glm::dot(axis, origin);
    const float rayOrigin = glm::dot(ray.direction, origin);
    const float originLength2 = glm::dot(origin, origin);
    const float a = axisLength2 - axisRay * axisRay;
    const float b = axisLength2 * rayOrigin - axisOrigin * axisRay;
    const float c = axisLength2 * originLength2 - axisOrigin * axisOrigin
                  - radius * radius * axisLength2;
    if (std::abs(a) > 1.0e-12F) {
        const float discriminant = b * b - a * c;
        if (discriminant >= 0.0F) {
            const float distance = (-b - std::sqrt(discriminant)) / a;
            const float axial = axisOrigin + distance * axisRay;
            if (distance >= 0.0F && axial >= 0.0F && axial <= axisLength2) {
                return distance;
            }
        }
    }
    const auto first = raySphere(ray, start, radius);
    const auto second = raySphere(ray, end, radius);
    if (first && second) return std::min(*first, *second);
    return first ? first : second;
}

inline std::optional<float> rayBox(
    const Ray& ray,
    const glm::vec3& center,
    const glm::vec3& axisX,
    const glm::vec3& axisY,
    const glm::vec3& axisZ) {
    const glm::mat3 basis(axisX, axisY, axisZ);
    if (std::abs(glm::determinant(basis)) < 1.0e-12F) return std::nullopt;
    const glm::mat3 inverse = glm::inverse(basis);
    const glm::vec3 origin = inverse * (ray.origin - center);
    const glm::vec3 direction = inverse * ray.direction;
    float near = 0.0F;
    float far = std::numeric_limits<float>::max();
    for (int axis = 0; axis < 3; ++axis) {
        if (std::abs(direction[axis]) < 1.0e-12F) {
            if (origin[axis] < -0.5F || origin[axis] > 0.5F) return std::nullopt;
            continue;
        }
        float first = (-0.5F - origin[axis]) / direction[axis];
        float second = (0.5F - origin[axis]) / direction[axis];
        if (first > second) std::swap(first, second);
        near = std::max(near, first);
        far = std::min(far, second);
        if (near > far) return std::nullopt;
    }
    return far >= 0.0F ? std::optional<float>(near) : std::nullopt;
}

}  // namespace nadoc_vr
