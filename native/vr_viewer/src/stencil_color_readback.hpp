#pragma once
#include <stdexcept>

// The NVIDIA stencil glReadPixels path waits for rendering even with a PBO.
// Preserve all eight stencil bits in an integer color target on the GPU, then
// use the ordinary asynchronous color-transfer path. This is diagnostic only.
class StencilColorReadback {
    GLuint program_=0,vao_=0,texture_=0,framebuffer_=0;
    int size_=0;
    static GLuint shader(GLenum kind,const char* source) {
        const auto result=glCreateShader(kind);glShaderSource(result,1,&source,nullptr);glCompileShader(result);
        GLint ok=0;glGetShaderiv(result,GL_COMPILE_STATUS,&ok);
        if(!ok){glDeleteShader(result);throw std::runtime_error("Cannot compile stencil diagnostic conversion");}
        return result;
    }
public:
    void initialize(int size) {
        size_=size;
        const auto vertex=shader(GL_VERTEX_SHADER,"#version 430 core\nvoid main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(p*2.-1.,0,1);}");
        const auto fragment=shader(GL_FRAGMENT_SHADER,"#version 430 core\nlayout(binding=0) uniform usampler2D sourceStencil;layout(location=0) out uint tag;void main(){tag=texelFetch(sourceStencil,ivec2(gl_FragCoord.xy),0).r;}");
        program_=glCreateProgram();glAttachShader(program_,vertex);glAttachShader(program_,fragment);glLinkProgram(program_);
        glDeleteShader(vertex);glDeleteShader(fragment);GLint ok=0;glGetProgramiv(program_,GL_LINK_STATUS,&ok);
        if(!ok)throw std::runtime_error("Cannot link stencil diagnostic conversion");
        glGenVertexArrays(1,&vao_);glGenTextures(1,&texture_);glBindTexture(GL_TEXTURE_2D,texture_);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        glTexImage2D(GL_TEXTURE_2D,0,GL_R8UI,size,size,0,GL_RED_INTEGER,GL_UNSIGNED_BYTE,nullptr);
        glGenFramebuffers(1,&framebuffer_);glBindFramebuffer(GL_FRAMEBUFFER,framebuffer_);
        glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,texture_,0);
        if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE)throw std::runtime_error("Stencil diagnostic target incomplete");
        glBindFramebuffer(GL_FRAMEBUFFER,0);
    }
    void read(GLuint source,void* pboOffset) const {
        GLint draw=0,read=0,program=0,vao=0,active=0,texture=0,sampler=0,viewport[4];GLboolean mask[4];
        glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING,&draw);glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING,&read);
        glGetIntegerv(GL_CURRENT_PROGRAM,&program);glGetIntegerv(GL_VERTEX_ARRAY_BINDING,&vao);
        glGetIntegerv(GL_ACTIVE_TEXTURE,&active);glActiveTexture(GL_TEXTURE0);
        glGetIntegerv(GL_TEXTURE_BINDING_2D,&texture);glGetIntegerv(GL_SAMPLER_BINDING,&sampler);
        glGetIntegerv(GL_VIEWPORT,viewport);glGetBooleanv(GL_COLOR_WRITEMASK,mask);
        constexpr GLenum caps[]={GL_DEPTH_TEST,GL_STENCIL_TEST,GL_BLEND,GL_SCISSOR_TEST,GL_CULL_FACE,GL_COLOR_LOGIC_OP};
        GLboolean enabled[6];for(size_t i=0;i<6;++i){enabled[i]=glIsEnabled(caps[i]);glDisable(caps[i]);}
        glBindFramebuffer(GL_FRAMEBUFFER,framebuffer_);glViewport(0,0,size_,size_);glColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE);
        glUseProgram(program_);glBindVertexArray(vao_);glBindSampler(0,0);glBindTexture(GL_TEXTURE_2D,source);
        glDrawArrays(GL_TRIANGLES,0,3);
        glReadPixels(0,0,size_,size_,GL_RED_INTEGER,GL_UNSIGNED_BYTE,pboOffset);
        glBindTexture(GL_TEXTURE_2D,texture);glBindSampler(0,sampler);glActiveTexture(active);
        glUseProgram(program);glBindVertexArray(vao);glViewport(viewport[0],viewport[1],viewport[2],viewport[3]);
        glColorMask(mask[0],mask[1],mask[2],mask[3]);
        for(size_t i=0;i<6;++i)if(enabled[i])glEnable(caps[i]);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER,draw);glBindFramebuffer(GL_READ_FRAMEBUFFER,read);
    }
    void shutdown() {
        if(framebuffer_)glDeleteFramebuffers(1,&framebuffer_);
        if(texture_)glDeleteTextures(1,&texture_);
        if(vao_)glDeleteVertexArrays(1,&vao_);
        if(program_)glDeleteProgram(program_);
        framebuffer_=texture_=vao_=program_=0;
    }
};
