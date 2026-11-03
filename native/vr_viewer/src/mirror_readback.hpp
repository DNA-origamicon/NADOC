#pragma once
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <vector>

// One bounded diagnostic readback. Polling never waits for the GPU. Call
// shutdown while the owning GL context is current, before destroying it.
class MirrorReadback {
    GLuint buffer_=0;
    GLsync fence_=nullptr;
    size_t bytes_=0;
    GLint previous_=0;
public:
    bool pending() const { return fence_!=nullptr; }
    void begin(size_t bytes) {
        if(pending()) throw std::logic_error("Mirror readback already pending");
        glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING,&previous_);
        if(!buffer_) glGenBuffers(1,&buffer_);
        glBindBuffer(GL_PIXEL_PACK_BUFFER,buffer_);
        if(bytes_!=bytes) {glBufferData(GL_PIXEL_PACK_BUFFER,bytes,nullptr,GL_STREAM_READ);bytes_=bytes;}
    }
    void finish() {
        fence_=glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);
        glBindBuffer(GL_PIXEL_PACK_BUFFER,previous_);
        if(!fence_) throw std::runtime_error("Cannot fence mirror diagnostics");
        // Submission of the ordinary eye frame flushes this context.
    }
    std::optional<std::vector<uint8_t>> poll() {
        if(!fence_) return {};
        const auto status=glClientWaitSync(fence_,0,0);
        if(status==GL_TIMEOUT_EXPIRED) return {};
        if(status==GL_WAIT_FAILED) throw std::runtime_error("Mirror diagnostic fence failed");
        GLint previous=0;glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING,&previous);
        glBindBuffer(GL_PIXEL_PACK_BUFFER,buffer_);
        const auto* data=static_cast<const uint8_t*>(glMapBufferRange(GL_PIXEL_PACK_BUFFER,0,bytes_,GL_MAP_READ_BIT));
        std::vector<uint8_t> result;
        if(data) result.assign(data,data+bytes_);
        const bool valid=data && glUnmapBuffer(GL_PIXEL_PACK_BUFFER)==GL_TRUE;
        glBindBuffer(GL_PIXEL_PACK_BUFFER,previous);
        glDeleteSync(fence_);fence_=nullptr;
        if(!valid) throw std::runtime_error("Mirror diagnostic mapping failed");
        return result;
    }
    void shutdown() {
        if(fence_)glDeleteSync(fence_);
        if(buffer_)glDeleteBuffers(1,&buffer_);
        fence_=nullptr;buffer_=0;bytes_=0;
    }
};
