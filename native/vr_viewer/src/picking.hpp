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

/** Intersect the closed +basisX half-cylinder used by the render mesh.
 *
 * The radial basis intentionally duplicates the cylinder vertex shader. This
 * includes the curved wall, flat diametral face, and both half-disc caps, so a
 * controller cannot hit the absent curved half that the old capsule proxy added.
 */
inline std::optional<float> rayHalfCylinder(
    const Ray& ray, const glm::vec3& start, const glm::vec3& end, float radius) {
    const glm::vec3 delta = end - start;
    const float length = glm::length(delta);
    if (length < 1.0e-6F || radius <= 0.0F) return std::nullopt;
    const glm::vec3 axis = delta / length;
    const glm::vec3 helper = std::abs(axis.z) < 0.95F
        ? glm::vec3(0, 0, 1) : glm::vec3(0, 1, 0);
    const glm::vec3 basisX = glm::normalize(glm::cross(helper, axis));
    const glm::vec3 basisY = glm::cross(axis, basisX);
    const glm::vec3 offset = ray.origin - start;
    const glm::vec3 origin(
        glm::dot(offset, basisX), glm::dot(offset, basisY), glm::dot(offset, axis));
    const glm::vec3 direction(
        glm::dot(ray.direction, basisX), glm::dot(ray.direction, basisY),
        glm::dot(ray.direction, axis));
    constexpr float epsilon = 1.0e-6F;
    float nearest = std::numeric_limits<float>::max();
    auto consider = [&](float distance, bool onSurface) {
        if (distance >= 0.0F && onSurface) nearest = std::min(nearest, distance);
    };

    const float radialA = direction.x * direction.x + direction.y * direction.y;
    if (radialA > 1.0e-12F) {
        const float radialB = 2.0F * (
            origin.x * direction.x + origin.y * direction.y);
        const float radialC = origin.x * origin.x + origin.y * origin.y
                            - radius * radius;
        const float discriminant = radialB * radialB - 4.0F * radialA * radialC;
        if (discriminant >= 0.0F) {
            const float root = std::sqrt(discriminant);
            const float first = (-radialB - root) / (2.0F * radialA);
            const float second = (-radialB + root) / (2.0F * radialA);
            for (float distance : {first, second}) {
                const float x = origin.x + direction.x * distance;
                const float z = origin.z + direction.z * distance;
                consider(distance, x >= -epsilon && z >= -epsilon && z <= length + epsilon);
            }
        }
    }

    if (std::abs(direction.x) > 1.0e-12F) {
        const float distance = -origin.x / direction.x;
        const float y = origin.y + direction.y * distance;
        const float z = origin.z + direction.z * distance;
        consider(
            distance,
            std::abs(y) <= radius + epsilon && z >= -epsilon && z <= length + epsilon);
    }

    if (std::abs(direction.z) > 1.0e-12F) {
        for (float cap : {0.0F, length}) {
            const float distance = (cap - origin.z) / direction.z;
            const float x = origin.x + direction.x * distance;
            const float y = origin.y + direction.y * distance;
            consider(
                distance,
                x >= -epsilon && x * x + y * y <= radius * radius + epsilon);
        }
    }
    return nearest < std::numeric_limits<float>::max()
        ? std::optional<float>(nearest) : std::nullopt;
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
