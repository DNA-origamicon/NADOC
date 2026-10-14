#pragma once

#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <cmath>
#include <fstream>
#include <istream>
#include <stdexcept>
#include <string>

namespace nadoc_vr {

// A presentation must remain a proper uniform similarity: no reflected,
// sheared, projective, nonfinite, or collapsed design in the physical view.
inline float validatedPresentationScale(const glm::mat4& matrix) {
    for(int column=0;column<4;++column)for(int row=0;row<4;++row)
        if(!std::isfinite(matrix[column][row]))throw std::runtime_error("Nonfinite presentation matrix");
    for(int column=0;column<4;++column)
        if(std::abs(matrix[column][3]-(column==3?1.F:0.F))>1.e-5F)
            throw std::runtime_error("Projective presentation matrix");
    const float scale=glm::length(glm::vec3(matrix[0]));
    if(!std::isfinite(scale) || scale<=0)throw std::runtime_error("Collapsed presentation matrix");
    const auto rotation=glm::mat3(matrix)/scale;
    const auto gram=glm::transpose(rotation)*rotation;
    for(int column=0;column<3;++column)for(int row=0;row<3;++row)
        if(std::abs(gram[column][row]-(column==row?1.F:0.F))>2.e-5F)
            throw std::runtime_error("Nonuniform or sheared presentation matrix");
    if(std::abs(glm::determinant(rotation)-1.F)>2.e-5F)
        throw std::runtime_error("Reflected presentation matrix");
    return scale;
}

inline glm::mat4 presentationNormalization(const glm::vec3& center,float scale,const glm::vec3& offset) {
    if(!std::isfinite(scale) || scale<=0)throw std::runtime_error("Invalid presentation normalization scale");
    for(int axis=0;axis<3;++axis)
        if(!std::isfinite(center[axis]) || !std::isfinite(offset[axis]))
            throw std::runtime_error("Nonfinite presentation normalization");
    return glm::translate(glm::mat4(1),offset-scale*center)
         * glm::scale(glm::mat4(1),glm::vec3(scale));
}

struct SavedPresentation {
    glm::mat4 modelToTracking{1};
    glm::vec3 sourceCenter{};
    float normalizationScale=1;
    glm::vec3 normalizedOffset{};

    glm::mat4 forNormalization(const glm::vec3& center,float scale,const glm::vec3& offset) const {
        (void)validatedPresentationScale(modelToTracking);
        const auto result=modelToTracking*presentationNormalization(sourceCenter,normalizationScale,normalizedOffset)
                         *glm::inverse(presentationNormalization(center,scale,offset));
        (void)validatedPresentationScale(result);
        return result;
    }
};

// NADOCVR_PRESENTATION 1; 16 row-major matrix values; source center XYZ;
// normalization scale; normalized offset XYZ. No head pose or design geometry.
inline SavedPresentation readSavedPresentation(std::istream& input) {
    std::string magic;int version=0;
    if(!(input>>magic>>version) || magic!="NADOCVR_PRESENTATION" || version!=1)
        throw std::runtime_error("Unsupported presentation state format");
    SavedPresentation result;
    for(int row=0;row<4;++row)for(int column=0;column<4;++column)
        if(!(input>>result.modelToTracking[column][row]))throw std::runtime_error("Incomplete presentation matrix");
    for(int axis=0;axis<3;++axis)if(!(input>>result.sourceCenter[axis]))throw std::runtime_error("Incomplete presentation source center");
    if(!(input>>result.normalizationScale))throw std::runtime_error("Missing presentation normalization scale");
    for(int axis=0;axis<3;++axis)if(!(input>>result.normalizedOffset[axis]))throw std::runtime_error("Incomplete presentation offset");
    std::string trailing;
    if(input>>trailing)throw std::runtime_error("Unexpected trailing presentation data");
    (void)result.forNormalization(result.sourceCenter,result.normalizationScale,result.normalizedOffset);
    return result;
}

inline SavedPresentation loadSavedPresentation(const std::string& path) {
    std::ifstream input(path);
    if(!input)throw std::runtime_error("Cannot read presentation state: "+path);
    return readSavedPresentation(input);
}
} // namespace nadoc_vr
