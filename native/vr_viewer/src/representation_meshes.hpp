#pragma once
#include <cmath>
#include <vector>
#include <glm/glm.hpp>

namespace nadoc_vr {
inline void bindInstanceAttribute(GLuint vao, GLuint buffer, GLuint attribute,
                                  GLint count, GLsizei stride, size_t offset) {
    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, buffer);
    glEnableVertexAttribArray(attribute);
    glVertexAttribPointer(attribute, count, GL_FLOAT, GL_FALSE, stride, reinterpret_cast<void*>(offset));
    glVertexAttribDivisor(attribute, 1);
    glBindVertexArray(0);
}

template<class Box, class Include>
void includeMeshBounds(const Box& box, Include include) {
    if (glm::length(box.normals[0]) > 0) {
        include(box.center - box.axisX*.5F - box.axisY*.5F);
        include(box.center + box.axisX*.5F - box.axisY*.5F);
        include(box.center - box.axisX*.5F + box.axisY*.5F);
    } else {
        for (float x : {-.5F,.5F}) for (float y : {-.5F,.5F}) for (float z : {-.5F,.5F})
            include(box.center + box.axisX*x + box.axisY*y + box.axisZ*z);
    }
}
inline constexpr int triangleIndexOffset = 36;
inline constexpr int ellipsoidIndexOffset = 39;
inline constexpr int ellipsoidIndexCount = 16 * 12 * 6;
// Shared instance geometry: a triangle and an ellipsoid use the same affine
// axes as a box, preserving the existing shadow, object-ID and highlight passes.
template<class Vertex, class Index>
void appendRepresentationMeshes(std::vector<Vertex>& vertices, std::vector<Index>& indices) {
    auto first = static_cast<Index>(vertices.size());
    vertices.insert(vertices.end(), {{{-.5F,-.5F,0},{0,0,1}},
                                    {{.5F,-.5F,0},{0,0,1}},
                                    {{-.5F,.5F,0},{0,0,1}}});
    indices.insert(indices.end(), {first, static_cast<Index>(first+1), static_cast<Index>(first+2)});
    first = static_cast<Index>(vertices.size());
    constexpr float pi = 3.14159265358979323846F;
    for (int y=0; y<=12; ++y) for (int x=0; x<=16; ++x) {
        const float theta=pi*y/12, phi=2*pi*x/16;
        glm::vec3 n{std::sin(theta)*std::cos(phi),std::cos(theta),std::sin(theta)*std::sin(phi)};
        vertices.push_back({n*.5F,n});
    }
    for (int y=0; y<12; ++y) for (int x=0; x<16; ++x) {
        Index a=static_cast<Index>(first+y*17+x), b=static_cast<Index>(a+17);
        indices.insert(indices.end(),{a,static_cast<Index>(a+1),b,
            static_cast<Index>(a+1),static_cast<Index>(b+1),b});
    }
}
}
