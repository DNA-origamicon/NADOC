#pragma once
#include "frame_identity.hpp"
#ifndef GL_GLEXT_PROTOTYPES
#define GL_GLEXT_PROTOTYPES
#endif
#include <GL/gl.h>
#include <GL/glext.h>
#include <array>
#include <time.h>

namespace nadoc_vr {
// One opt-in shader draw into the actual acquired application eye texture.
// No GL readback/fence/finish. Initialize once, before measured rendering.
class SubmittedFrameMarker {
public:
    void configure(bool enabled,const std::string& session,bool journalEnabled) {
        configure(enabled?frame_identity::Mode::on:frame_identity::Mode::off,session,journalEnabled);
    }
    void configure(frame_identity::Mode mode,const std::string& session,bool journalEnabled) {
        if(program_)throw std::runtime_error("Frame marker cannot change after initialization");
        const bool enabled=mode!=frame_identity::Mode::off;
        if(enabled && !journalEnabled)throw std::runtime_error("Frame marker requires --pose-journal and a live session");
        session_=enabled?frame_identity::parseSession(session):frame_identity::Session{};mode_=mode;
    }
    bool enabled()const{return mode_!=frame_identity::Mode::off;}
    std::string json()const{return frame_identity::configJson(mode_,session_);}
    void initialize() {
        if(!enabled() || program_)return;
        glGetIntegerv(GL_MAX_DRAW_BUFFERS,&drawBuffers_);
        if(drawBuffers_<2 || drawBuffers_>int(State::maxDrawBuffers))
            throw std::runtime_error("Unsupported frame marker draw buffer count");
        const char* vertex=R"(#version 330 core
void main(){vec2 p=vec2((gl_VertexID&1)*2-1,(gl_VertexID>>1)*2-1);gl_Position=vec4(p,0,1);}
)";
        const char* fragment=R"(#version 330 core
uniform uint packet[8];
uniform ivec2 origin;
layout(location=0) out vec4 color;
layout(location=1) out uint objectId;
void main(){
 ivec2 p=ivec2(gl_FragCoord.xy)-origin;
 ivec2 c=ivec2(p.x/8,23-p.y/8);
 vec3 rgb=vec3(0);
 if((c.x<3 || c.x>=21) && (c.y<3 || c.y>=21))rgb=vec3(1);
 else if(c.x>=4 && c.x<20 && c.y>=4 && c.y<20){
  int bit=(c.y-4)*16+c.x-4;
  rgb=vec3(float((packet[bit/32]>>uint(31-bit%32))&1u));
 }
 color=vec4(rgb,1);objectId=0u;
}
)";
        GLuint vs=0,fs=0;
        try {
            vs=shader(GL_VERTEX_SHADER,vertex);fs=shader(GL_FRAGMENT_SHADER,fragment);
            program_=glCreateProgram();glAttachShader(program_,vs);glAttachShader(program_,fs);glLinkProgram(program_);
            GLint okay=0;glGetProgramiv(program_,GL_LINK_STATUS,&okay);
            if(!okay)throw std::runtime_error("Cannot link submitted frame marker shader");
            packetLocation_=glGetUniformLocation(program_,"packet[0]");originLocation_=glGetUniformLocation(program_,"origin");
            if(packetLocation_<0 || originLocation_<0)throw std::runtime_error("Missing frame marker shader uniforms");
            glGenVertexArrays(1,&vao_);
            if(!vao_)throw std::runtime_error("Cannot create frame marker vertex array");
        }catch(...){if(vs)glDeleteShader(vs);if(fs)glDeleteShader(fs);shutdown();throw;}
        glDeleteShader(vs);glDeleteShader(fs);
    }
    void shutdown() {
        if(vao_)glDeleteVertexArrays(1,&vao_);
        if(program_)glDeleteProgram(program_);
        vao_=program_=0;
    }
    frame_identity::Receipt draw(unsigned eye,uint32_t width,uint32_t height,uint64_t frame,
                                 bool idsAttached,bool classify,unsigned overlayClass,bool journalCollecting) {
        // Recording mode is a configured capability while idle. Only an armed
        // journal permits a draw; this early return performs no GL calls/clocks.
        if(!frame_identity::shouldRender(mode_,journalCollecting))return {};
        if(!program_)throw std::runtime_error("Frame marker not initialized");
        frame_identity::Receipt receipt;receipt.frame=frame;receipt.rect=frame_identity::rectangle(width,height);
        const auto packet=frame_identity::encode(session_,frame,eye);receipt.packetCrc32=frame_identity::packetCrc(packet);
        std::array<GLuint,8> words{};
        for(size_t i=0;i<words.size();++i)for(size_t b=0;b<4;++b)words[i]=(words[i]<<8)|packet[i*4+b];
        receipt.hostStartNs=journalCollecting?stamp():0;
        {
            State previous(drawBuffers_);
            const int y=int(height)-receipt.rect.y-receipt.rect.height;
            glViewport(receipt.rect.x,y,receipt.rect.width,receipt.rect.height);
            for(auto capability:State::disabledCapabilities)glDisable(capability);
            for(unsigned i=0;i<8;++i)glDisable(GL_CLIP_DISTANCE0+i);
            glDisablei(GL_BLEND,0);glDisablei(GL_BLEND,1);
            glColorMaski(0,GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE);glColorMaski(1,GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE);
            glPolygonMode(GL_FRONT_AND_BACK,GL_FILL);
            if(classify) {
                glEnable(GL_STENCIL_TEST);glStencilMask(0xffU);glStencilFunc(GL_ALWAYS,GLint(overlayClass),0xffU);
                glStencilOp(GL_KEEP,GL_KEEP,GL_REPLACE);
            }
            const GLenum buffers[2]={GL_COLOR_ATTACHMENT0,GLenum(idsAttached?GL_COLOR_ATTACHMENT1:GL_NONE)};
            glDrawBuffers(2,buffers);
            glUseProgram(program_);glBindVertexArray(vao_);
            glUniform1uiv(packetLocation_,8,words.data());glUniform2i(originLocation_,receipt.rect.x,y);
            glDrawArrays(GL_TRIANGLE_STRIP,0,4);
        }
        receipt.hostEndNs=journalCollecting?stamp():0;receipt.rendered=true;return receipt;
    }
private:
    frame_identity::Mode mode_=frame_identity::Mode::off;
    frame_identity::Session session_{};
    GLuint program_=0,vao_=0;
    GLint packetLocation_=-1,originLocation_=-1,drawBuffers_=0;
    static int64_t stamp() {timespec t{};if(clock_gettime(CLOCK_MONOTONIC,&t))return 0;return int64_t(t.tv_sec)*1000000000+t.tv_nsec;}
    static GLuint shader(GLenum type,const char* source) {
        const auto value=glCreateShader(type);glShaderSource(value,1,&source,nullptr);glCompileShader(value);
        GLint okay=0;glGetShaderiv(value,GL_COMPILE_STATUS,&okay);
        if(!okay){glDeleteShader(value);throw std::runtime_error("Cannot compile submitted frame marker shader");}
        return value;
    }
    struct Stencil {
        GLint function=0,reference=0,valueMask=0,writeMask=0,fail=0,zfail=0,zpass=0;
        explicit Stencil(bool back) {
            glGetIntegerv(back?GL_STENCIL_BACK_FUNC:GL_STENCIL_FUNC,&function);
            glGetIntegerv(back?GL_STENCIL_BACK_REF:GL_STENCIL_REF,&reference);
            glGetIntegerv(back?GL_STENCIL_BACK_VALUE_MASK:GL_STENCIL_VALUE_MASK,&valueMask);
            glGetIntegerv(back?GL_STENCIL_BACK_WRITEMASK:GL_STENCIL_WRITEMASK,&writeMask);
            glGetIntegerv(back?GL_STENCIL_BACK_FAIL:GL_STENCIL_FAIL,&fail);
            glGetIntegerv(back?GL_STENCIL_BACK_PASS_DEPTH_FAIL:GL_STENCIL_PASS_DEPTH_FAIL,&zfail);
            glGetIntegerv(back?GL_STENCIL_BACK_PASS_DEPTH_PASS:GL_STENCIL_PASS_DEPTH_PASS,&zpass);
        }
        void restore(GLenum face)const {
            glStencilFuncSeparate(face,function,reference,GLuint(valueMask));glStencilMaskSeparate(face,GLuint(writeMask));
            glStencilOpSeparate(face,fail,zfail,zpass);
        }
    };
    struct State {
        static constexpr size_t maxDrawBuffers=16;
        static constexpr std::array<GLenum,11> disabledCapabilities={GL_DEPTH_TEST,GL_STENCIL_TEST,GL_SCISSOR_TEST,
            GL_CULL_FACE,GL_RASTERIZER_DISCARD,GL_COLOR_LOGIC_OP,GL_DITHER,GL_SAMPLE_ALPHA_TO_COVERAGE,
            GL_SAMPLE_COVERAGE,GL_SAMPLE_MASK,GL_POLYGON_SMOOTH};
        GLint program=0,vao=0,viewport[4]{},polygon[2]{},count=0;
        std::array<GLenum,maxDrawBuffers> drawBuffers{};
        std::array<GLboolean,disabledCapabilities.size()> enabled{};
        std::array<GLboolean,8> clips{};
        GLboolean blend[2]{},colorMask[2][4]{};
        Stencil front{false},back{true};
        explicit State(GLint bufferCount):count(bufferCount) {
            glGetIntegerv(GL_CURRENT_PROGRAM,&program);glGetIntegerv(GL_VERTEX_ARRAY_BINDING,&vao);
            glGetIntegerv(GL_VIEWPORT,viewport);glGetIntegerv(GL_POLYGON_MODE,polygon);
            for(int i=0;i<count;++i){GLint value=0;glGetIntegerv(GL_DRAW_BUFFER0+i,&value);drawBuffers[i]=GLenum(value);}
            for(size_t i=0;i<enabled.size();++i)enabled[i]=glIsEnabled(disabledCapabilities[i]);
            for(unsigned i=0;i<clips.size();++i)clips[i]=glIsEnabled(GL_CLIP_DISTANCE0+i);
            for(unsigned i=0;i<2;++i){blend[i]=glIsEnabledi(GL_BLEND,i);glGetBooleani_v(GL_COLOR_WRITEMASK,i,colorMask[i]);}
        }
        ~State() {
            glUseProgram(program);glBindVertexArray(vao);glViewport(viewport[0],viewport[1],viewport[2],viewport[3]);
            glDrawBuffers(count,drawBuffers.data());glPolygonMode(GL_FRONT_AND_BACK,polygon[0]);
            front.restore(GL_FRONT);back.restore(GL_BACK);
            for(size_t i=0;i<enabled.size();++i)set(disabledCapabilities[i],enabled[i]);
            for(unsigned i=0;i<clips.size();++i)set(GL_CLIP_DISTANCE0+i,clips[i]);
            for(unsigned i=0;i<2;++i){if(blend[i])glEnablei(GL_BLEND,i);else glDisablei(GL_BLEND,i);
                glColorMaski(i,colorMask[i][0],colorMask[i][1],colorMask[i][2],colorMask[i][3]);}
        }
        static void set(GLenum capability,GLboolean enabled){if(enabled)glEnable(capability);else glDisable(capability);}
    };
};
} // namespace nadoc_vr
