#pragma once
#include <array>
#include "representations.hpp"
#include <GL/gl.h>
#include <glm/glm.hpp>

namespace nadoc_vr {
// One slot and one color per supported representation. GPU-local copies avoid re-running
// semantic ownership/color/coordinate loops on unchanged static geometry.
class RepresentationBuffers {
    struct Slot {
        bool valid=false;
        int color=0;
        std::array<GLuint,4> buffers{};
        std::array<GLint64,4> sizes{};
        std::array<GLsizei,4> counts{};
        glm::vec3 center{};
        float radius=0;
    };
    std::array<Slot,kRepresentationCount> slots_{};
    static void copy(GLuint source,GLuint destination,GLint64 size) {
        glBindBuffer(GL_COPY_WRITE_BUFFER,destination);
        glBufferData(GL_COPY_WRITE_BUFFER,size,nullptr,GL_DYNAMIC_DRAW);
        if(size) {
            glBindBuffer(GL_COPY_READ_BUFFER,source);
            glCopyBufferSubData(GL_COPY_READ_BUFFER,GL_COPY_WRITE_BUFFER,0,0,size);
        }
    }
 public:
    RepresentationBuffers()=default;
    RepresentationBuffers(const RepresentationBuffers&)=delete;
    RepresentationBuffers& operator=(const RepresentationBuffers&)=delete;
    ~RepresentationBuffers(){clear();}
    void invalidate(size_t index) {auto& slot=slots_.at(index);glDeleteBuffers(4,slot.buffers.data());slot=Slot{};}
    void clear() {
        for(auto& slot:slots_) {
            glDeleteBuffers(4,slot.buffers.data());
            slot=Slot{};
        }
    }
    bool restore(size_t representation,int color,const std::array<GLuint,4>& targets,
                 std::array<GLsizei,4>& counts,glm::vec3& center,float& radius) const {
        const auto& slot=slots_.at(representation);
        if(!slot.valid || slot.color!=color)return false;
        for(size_t i=0;i<4;++i)copy(slot.buffers[i],targets[i],slot.sizes[i]);
        counts=slot.counts;center=slot.center;radius=slot.radius;
        return true;
    }
    void capture(size_t representation,int color,const std::array<GLuint,4>& sources,
                 const std::array<GLsizei,4>& counts,glm::vec3 center,float radius) {
        auto& slot=slots_.at(representation);
        if(!slot.buffers[0])glGenBuffers(4,slot.buffers.data());
        for(size_t i=0;i<4;++i) {
            glBindBuffer(GL_COPY_READ_BUFFER,sources[i]);
            glGetBufferParameteri64v(GL_COPY_READ_BUFFER,GL_BUFFER_SIZE,&slot.sizes[i]);
            copy(sources[i],slot.buffers[i],slot.sizes[i]);
        }
        slot.counts=counts;slot.color=color;slot.center=center;slot.radius=radius;slot.valid=true;
    }
};
}
