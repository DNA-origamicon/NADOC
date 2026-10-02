#pragma once

// Packed, committed-pose instances for one selected owner. No semantic lookups
// or CPU allocation occur during motion. Included after the renderer instance types.
struct RigidPreviewGeometry {
    using Weights = std::pair<float, float>;
    template<class T> struct Channel {
        struct Edit { size_t index; Weights weights; };
        std::vector<T> original, current, beforeCommit;
        std::vector<Edit> edits;
        void add(const T& value, Weights weights) {
            if (weights.first != 0 || weights.second != 0)
                edits.push_back({original.size(), weights});
            original.push_back(value);
        }
        void finish() { current = original; }
        template<class Include> void includeFixed(Include include) const {
            size_t edit=0;
            for(size_t i=0;i<current.size();++i) {
                if(edit<edits.size() && edits[edit].index==i) {++edit;continue;}
                include(current[i]);
            }
        }
        template<class Include> void includeEdited(Include include) const {
            for(const auto& edit:edits) include(current[edit.index]);
        }
        void commit() {
            beforeCommit.clear(); beforeCommit.reserve(edits.size());
            for (const auto& edit : edits) {
                beforeCommit.push_back(original[edit.index]);
                original[edit.index] = current[edit.index];
            }
        }
        void undoCommit() {
            for (size_t i = 0; i < edits.size(); ++i)
                original[edits[i].index] = beforeCommit[i];
            beforeCommit.clear();
        }
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
    bool hasCommittedBaseline = false;
    glm::vec3 fixedLo{std::numeric_limits<float>::max()};
    glm::vec3 fixedHi{std::numeric_limits<float>::lowest()};
    Channel<Vertex> points, glowPoints;
    Channel<Cylinder> cylinders, glowCylinders, halves, glowHalves;
    Channel<Box> boxes, glowBoxes;
    void clear() { *this = {}; }
    bool active() const { return !token.empty(); }
    void finish() {
        points.finish(); glowPoints.finish(); cylinders.finish(); glowCylinders.finish();
        halves.finish(); glowHalves.finish(); boxes.finish(); glowBoxes.finish();
        fixedLo=glm::vec3(std::numeric_limits<float>::max());
        fixedHi=glm::vec3(std::numeric_limits<float>::lowest());
        auto include=[&](glm::vec3 p,float r=0){fixedLo=glm::min(fixedLo,p-glm::vec3(r));fixedHi=glm::max(fixedHi,p+glm::vec3(r));};
        points.includeFixed([&](const auto& v){include(v.position,v.size);});
        for(const auto* channel:{&cylinders,&halves})
            channel->includeFixed([&](const auto& v){include(v.start,v.radius);include(v.end,v.radius);});
        boxes.includeFixed([&](const auto& v){nadoc_vr::includeMeshBounds(v,include);});
    }
    void commit() {
        points.commit(); glowPoints.commit(); cylinders.commit(); glowCylinders.commit();
        halves.commit(); glowHalves.commit(); boxes.commit(); glowBoxes.commit();
        hasCommittedBaseline = true;
    }
    void undoCommit() {
        points.undoCommit(); glowPoints.undoCommit(); cylinders.undoCommit(); glowCylinders.undoCommit();
        halves.undoCommit(); glowHalves.undoCommit(); boxes.undoCommit(); glowBoxes.undoCommit();
        hasCommittedBaseline = false;
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
        glm::vec3 lo=fixedLo, hi=fixedHi;
        auto include = [&](glm::vec3 p, float r = 0) {
            lo = glm::min(lo, p - glm::vec3(r)); hi = glm::max(hi, p + glm::vec3(r));
        };
        points.includeEdited([&](const auto& v){include(v.position,v.size);});
        for (const auto* channel : {&cylinders, &halves})
            channel->includeEdited([&](const auto& v){include(v.start,v.radius);include(v.end,v.radius);});
        boxes.includeEdited([&](const auto& v){nadoc_vr::includeMeshBounds(v,include);});
        if (points.current.empty() && cylinders.current.empty() && halves.current.empty() && boxes.current.empty()) return;
        center = (lo + hi) * .5F;
        radius = std::max(glm::length(hi - lo) * .5F, .01F);
    }
};
