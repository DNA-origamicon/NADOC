#pragma once
#include "picking.hpp"
#include "representations.hpp"
#include <glm/gtc/matrix_inverse.hpp>

namespace nadoc_vr {
inline std::optional<float> rayRepresentationMesh(Representation rep, const Ray& ray,
    const glm::vec3& center, const glm::vec3& x, const glm::vec3& y, const glm::vec3& z) {
    if (rep == Representation::surface || rep == Representation::surfaceDetail || rep == Representation::hull) {
        const glm::vec3 p = glm::cross(ray.direction, y);
        const float det = glm::dot(x,p);
        if (std::abs(det) < 1e-12F) return std::nullopt;
        const glm::vec3 offset = ray.origin - (center-(x+y)*.5F);
        const float u=glm::dot(offset,p)/det;
        const glm::vec3 q=glm::cross(offset,x);
        const float v=glm::dot(ray.direction,q)/det, t=glm::dot(y,q)/det;
        return u>=0 && v>=0 && u+v<=1 && t>=0 ? std::optional<float>(t) : std::nullopt;
    }
    if (rep == Representation::oxdna) {
        const glm::mat3 axes(x,y,z);
        if (std::abs(glm::determinant(axes)) < 1e-18F) return std::nullopt;
        const glm::mat3 inverse=glm::inverse(axes);
        const glm::vec3 direction=inverse*ray.direction;
        const float scale=glm::length(direction);
        if (scale < 1e-12F) return std::nullopt;
        const auto hit=raySphere({inverse*(ray.origin-center),direction/scale},{0,0,0},.5F);
        return hit ? std::optional<float>(*hit/scale) : std::nullopt;
    }
    return rayBox(ray,center,x,y,z);
}
}
