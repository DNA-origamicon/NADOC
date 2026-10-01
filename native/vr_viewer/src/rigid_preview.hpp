#pragma once

// Packed, committed-pose instances for one selected owner. No semantic lookups
// or CPU allocation occur during motion. Included after the renderer instance types.
struct RigidPreviewGeometry {
    using Weights = std::pair<float, float>;
    template<class T> struct Channel {
        struct Edit { size_t index; Weights weights; };
        std::vector<T> original, current;
        std::vector<Edit> edits;
        void add(const T& value, Weights weights) {
            if (weights.first != 0 || weights.second != 0)
                edits.push_back({original.size(), weights});
            original.push_back(value);
        }
        void finish() { current = original; }
        template<class Transform> void apply(Transform transform) {
            for (const auto& edit : edits) {
                current[edit.index] = original[edit.index];
                transform(current[edit.index], edit.weights);
            }
        }
        void upload(GLuint buffer) const {
            if (edits.empty()) return;
            // Orphan in-flight storage rather than waiting for the previous eye
            // draws. Identity/color/radius bytes are copied without recomputation.
            glBindBuffer(GL_ARRAY_BUFFER, buffer);
            const auto bytes = static_cast<GLsizeiptr>(current.size() * sizeof(T));
            glBufferData(GL_ARRAY_BUFFER, bytes, nullptr, GL_STREAM_DRAW);
            glBufferSubData(GL_ARRAY_BUFFER, 0, bytes, current.data());
        }
    };
    std::string token;
    Channel<Vertex> points, glowPoints;
    Channel<Cylinder> cylinders, glowCylinders, halves, glowHalves;
    Channel<Box> boxes, glowBoxes;
    void clear() { *this = {}; }
    bool active() const { return !token.empty(); }
    void finish() {
        points.finish(); glowPoints.finish(); cylinders.finish(); glowCylinders.finish();
        halves.finish(); glowHalves.finish(); boxes.finish(); glowBoxes.finish();
    }
    void apply(const glm::mat4& transform) {
        auto point = [&](Vertex& v, Weights w) {
            v.position = nadoc_vr::weightedTransformPoint(v.position, transform, w.first);
        };
        auto cylinder = [&](Cylinder& v, Weights w) {
            v.start = nadoc_vr::weightedTransformPoint(v.start, transform, w.first);
            v.end = nadoc_vr::weightedTransformPoint(v.end, transform, w.second);
        };
        auto box = [&](Box& v, Weights w) {
            v.center = nadoc_vr::weightedTransformPoint(v.center, transform, w.first);
            for (auto* axis : {&v.axisX, &v.axisY, &v.axisZ})
                *axis = nadoc_vr::weightedTransformVector(*axis, transform, w.first);
            for (auto& normal : v.normals)
                normal = nadoc_vr::weightedTransformVector(normal, transform, w.first);
        };
        points.apply(point); glowPoints.apply(point);
        cylinders.apply(cylinder); glowCylinders.apply(cylinder);
        halves.apply(cylinder); glowHalves.apply(cylinder);
        boxes.apply(box); glowBoxes.apply(box);
    }
    void bounds(glm::vec3& center, float& radius) const {
        glm::vec3 lo(std::numeric_limits<float>::max()), hi(std::numeric_limits<float>::lowest());
        auto include = [&](glm::vec3 p, float r = 0) {
            lo = glm::min(lo, p - glm::vec3(r)); hi = glm::max(hi, p + glm::vec3(r));
        };
        for (const auto& v : points.current) include(v.position, v.size);
        for (const auto* channel : {&cylinders, &halves})
            for (const auto& v : channel->current) { include(v.start, v.radius); include(v.end, v.radius); }
        for (const auto& v : boxes.current) nadoc_vr::includeMeshBounds(v, include);
        if (points.current.empty() && cylinders.current.empty() && halves.current.empty() && boxes.current.empty()) return;
        center = (lo + hi) * .5F;
        radius = std::max(glm::length(hi - lo) * .5F, .01F);
    }
};
