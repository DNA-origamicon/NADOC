#define GL_GLEXT_PROTOTYPES
#include <GLFW/glfw3.h>
#include "view_opaque_shader.hpp"
#if defined(NADOC_TEST_INSTANCE_GROUPS) || defined(NADOC_TEST_INDEXED_MESH)
#include "view_instance_groups.hpp"
#endif
#ifdef NADOC_TEST_INDEXED_MESH
#include "view_indexed_mesh.hpp"
#endif
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <vector>
using namespace nadoc_vr::view_opaque;
struct V {glm::vec3 p;glm::vec4 color;glm::vec2 uv;glm::vec3 normal;};
struct I {glm::mat4 matrix;glm::vec4 color;};
static_assert(sizeof(V)==48 && sizeof(I)==80);
std::string sourceLiteral(const char* name,const char* declaration) {
    const auto path=std::filesystem::path(NADOC_SOURCE_ROOT)/"native/vr_viewer/src"/name;
    std::ifstream file(path);assert(file);std::string s{std::istreambuf_iterator<char>(file),{}};
    const auto a=s.find(declaration);assert(a!=std::string::npos);
    const auto start=s.find("R\"GLSL(",a);assert(start!=std::string::npos);
    const auto end=s.find(")GLSL\"",start);assert(end!=std::string::npos);
    return s.substr(start+7,end-start-7);
}
GLuint shader(GLenum type,const char* source) {
    auto id=glCreateShader(type);glShaderSource(id,1,&source,nullptr);glCompileShader(id);GLint ok=0;glGetShaderiv(id,GL_COMPILE_STATUS,&ok);
    if(!ok){char log[4096]{};glGetShaderInfoLog(id,sizeof(log),nullptr,log);std::cerr<<log;assert(false);}return id;
}
GLuint program(bool opaque,const std::string& lit,const std::string& glass,bool grouped=false) {
    std::string vertex(vertexSource);
#if defined(NADOC_TEST_INSTANCE_GROUPS) || defined(NADOC_TEST_INDEXED_MESH)
    if(grouped)vertex=nadoc_vr::view_groups::vertexShader(vertex);
#else
    (void)grouped;
#endif
    const auto f=fragment(lit,glass,opaque);auto vs=shader(GL_VERTEX_SHADER,vertex.c_str()),fs=shader(GL_FRAGMENT_SHADER,f.c_str());
    auto p=glCreateProgram();glAttachShader(p,vs);glAttachShader(p,fs);
#ifdef NADOC_TEST_INDEXED_MESH
    const char* varyings[]={"gl_Position","vNormal","c","t","vWorldPosition","vColor","vTwoSided","vSelection","vObjectId"};glTransformFeedbackVaryings(p,9,varyings,GL_INTERLEAVED_ATTRIBS);
#elif defined(NADOC_TEST_INSTANCE_GROUPS)
    const char* varyings[]={"gl_Position","vNormal","c","t"};glTransformFeedbackVaryings(p,4,varyings,GL_INTERLEAVED_ATTRIBS);
#endif
    glLinkProgram(p);GLint ok=0;glGetProgramiv(p,GL_LINK_STATUS,&ok);
    if(!ok){char log[4096]{};glGetProgramInfoLog(p,sizeof(log),nullptr,log);std::cerr<<log;assert(false);}glDeleteShader(vs);glDeleteShader(fs);return p;
}
struct Pixels {std::vector<unsigned char> color,stencil;std::vector<float> depth;std::vector<GLuint> ids;};
#ifdef NADOC_TEST_INDEXED_MESH
// Unit-sphere base only, copied byte-for-byte from the actual exported mesh.
// This retains real seam/pole normals, UVs and signed floating-point values.
std::vector<V> sphereMesh() {
    std::ifstream file(std::filesystem::path(NADOC_SOURCE_ROOT)/"native/vr_viewer/tests/fixtures/exported_sphere_420.bin",std::ios::binary);
    std::vector<V> out(420);assert(file.read(reinterpret_cast<char*>(out.data()),out.size()*sizeof(V)));
    assert(file.peek()==std::char_traits<char>::eof());
    const auto indexed=nadoc_vr::view_indexed::build(out);assert(indexed.plan.eligible && indexed.vertices.size()==91);
    return out;
}
bool samePixels(const Pixels& a,const Pixels& b) {
    return a.color==b.color && a.depth==b.depth && a.ids==b.ids && a.stencil==b.stencil;
}
#endif
int main() {
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);glfwWindowHint(GLFW_OPENGL_PROFILE,GLFW_OPENGL_CORE_PROFILE);
    auto* window=glfwCreateWindow(128,128,"Opaque exact lighting/depth contract",nullptr,nullptr);if(!window){glfwTerminate();return 77;}glfwMakeContextCurrent(window);
    const auto lit=sourceLiteral("main.cpp","constexpr const char* kLitFragmentSource");
    const auto glass=sourceLiteral("frosted_glass.hpp","inline constexpr const char* frostedGlassShader");
    const auto legacy=program(false,lit,glass),opaque=program(true,lit,glass);
#ifdef NADOC_TEST_INSTANCE_GROUPS
    const auto groupLegacy=program(false,lit,glass,true),groupOpaque=program(true,lit,glass,true);
    GLuint groupedVbo=0,instanceTex=0,feedback=0;glGenBuffers(1,&groupedVbo);glGenTextures(1,&instanceTex);glGenBuffers(1,&feedback);
    size_t feedbackCompared=0;
#endif
#ifdef NADOC_TEST_INDEXED_MESH
    GLuint indexedVbo=0,indexBuffer=0,feedback=0;glGenBuffers(1,&indexedVbo);glGenBuffers(1,&indexBuffer);glGenBuffers(1,&feedback);
    const auto groupLegacy=program(false,lit,glass,true),groupOpaque=program(true,lit,glass,true);
    GLuint groupedVbo=0,groupIndexBuffer=0,instanceTex=0;glGenBuffers(1,&groupedVbo);glGenBuffers(1,&groupIndexBuffer);glGenTextures(1,&instanceTex);
    size_t feedbackCompared=0,shadowCovered=0,groupedFeedbackCompared=0;unsigned indexedCompared=0,groupedCompared=0,groupFallbackCompared=0;
#endif
    GLuint vao=0,vbo=0,ibo=0;glGenVertexArrays(1,&vao);glBindVertexArray(vao);glGenBuffers(1,&vbo);glGenBuffers(1,&ibo);
    glBindBuffer(GL_ARRAY_BUFFER,vbo);
    for(auto a:{0U,1U,2U,8U})glEnableVertexAttribArray(a);
    glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,p));glVertexAttribPointer(1,4,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,color));
    glVertexAttribPointer(2,2,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,uv));glVertexAttribPointer(8,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,normal));
    glBindBuffer(GL_ARRAY_BUFFER,ibo);for(GLuint a=3;a<=7;++a){glEnableVertexAttribArray(a);glVertexAttribDivisor(a,1);glVertexAttribPointer(a,4,GL_FLOAT,GL_FALSE,sizeof(I),(void*)(uintptr_t)((a-3)*sizeof(glm::vec4)));}
    GLuint framebuffer=0;std::array<GLuint,3> outputs{};glGenFramebuffers(1,&framebuffer);glBindFramebuffer(GL_FRAMEBUFFER,framebuffer);glGenTextures(3,outputs.data());
    for(unsigned i=0;i<3;++i) {
        glBindTexture(GL_TEXTURE_2D,outputs[i]);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
#ifdef NADOC_TEST_INDEXED_MESH
        glTexImage2D(GL_TEXTURE_2D,0,i==0?GL_RGBA8:i==1?GL_DEPTH32F_STENCIL8:GL_R32UI,128,128,0,i==0?GL_RGBA:i==1?GL_DEPTH_STENCIL:GL_RED_INTEGER,i==0?GL_UNSIGNED_BYTE:i==1?GL_FLOAT_32_UNSIGNED_INT_24_8_REV:GL_UNSIGNED_INT,nullptr);
        glFramebufferTexture2D(GL_FRAMEBUFFER,i==0?GL_COLOR_ATTACHMENT0:i==1?GL_DEPTH_STENCIL_ATTACHMENT:GL_COLOR_ATTACHMENT1,GL_TEXTURE_2D,outputs[i],0);
#else
        glTexImage2D(GL_TEXTURE_2D,0,i==0?GL_RGBA8:i==1?GL_DEPTH_COMPONENT32F:GL_R32UI,128,128,0,i==0?GL_RGBA:i==1?GL_DEPTH_COMPONENT:GL_RED_INTEGER,i==0?GL_UNSIGNED_BYTE:i==1?GL_FLOAT:GL_UNSIGNED_INT,nullptr);
        glFramebufferTexture2D(GL_FRAMEBUFFER,i==0?GL_COLOR_ATTACHMENT0:i==1?GL_DEPTH_ATTACHMENT:GL_COLOR_ATTACHMENT1,GL_TEXTURE_2D,outputs[i],0);
#endif
    }
    const GLenum buffers[]={GL_COLOR_ATTACHMENT0,GL_COLOR_ATTACHMENT1};glDrawBuffers(2,buffers);assert(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE);
    GLuint shadow=0,atlas=0;glGenTextures(1,&shadow);glActiveTexture(GL_TEXTURE0);glBindTexture(GL_TEXTURE_2D,shadow);
    std::vector<float> shadowDepth(2048*2048);for(unsigned y=0;y<2048;++y)for(unsigned x=0;x<2048;++x)shadowDepth[y*2048+x]=((x/64+y/64)%3)? .40F:.80F;
    glTexImage2D(GL_TEXTURE_2D,0,GL_DEPTH_COMPONENT32F,2048,2048,0,GL_DEPTH_COMPONENT,GL_FLOAT,shadowDepth.data());
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_COMPARE_MODE,GL_COMPARE_REF_TO_TEXTURE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_COMPARE_FUNC,GL_LEQUAL);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
    glGenTextures(1,&atlas);glActiveTexture(GL_TEXTURE1);glBindTexture(GL_TEXTURE_2D,atlas);const std::array<unsigned char,4> white{255,255,255,255};glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,1,1,0,GL_RGBA,GL_UNSIGNED_BYTE,white.data());glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    std::vector<V> vertices;
    for(auto p:std::array<glm::vec3,6>{{{-.75F,-.70F,0},{.75F,-.70F,0},{.75F,.70F,0},{-.75F,-.70F,0},{.75F,.70F,0},{-.75F,.70F,0}}})vertices.push_back({p,{.17F+p.x*.1F,.43F+p.y*.15F,.71F,1},{-1,-1},{.2F,.3F,1}});
    unsigned compared=0,covered=0;size_t shadowChanged=0;std::vector<unsigned char> noShadow;
#if defined(NADOC_TEST_INSTANCE_GROUPS) || defined(NADOC_TEST_INDEXED_MESH)
    constexpr unsigned cases=32;
#else
    constexpr unsigned cases=24;
#endif
    for(unsigned trial=0;trial<cases;++trial) {
        auto mesh=vertices;
#ifdef NADOC_TEST_INDEXED_MESH
        if((trial/2)%2)mesh=sphereMesh();
        else {mesh.clear();for(unsigned k=0;k<75;++k)mesh.push_back(vertices[k%vertices.size()]);}
#endif
        for(auto& v:mesh)if(trial%6==5)v.normal=glm::vec3(0);
        if((trial/2)%2)for(size_t k=0;k<mesh.size();k+=3)std::swap(mesh[k],mesh[k+1]); // exact backfaces
#ifdef NADOC_TEST_INSTANCE_GROUPS
        const auto base=mesh;const std::array<unsigned,4> repetitions{1,3,6,12};
        for(unsigned repeat=1;repeat<repetitions[trial%4];++repeat)mesh.insert(mesh.end(),base.begin(),base.end());
#endif
        std::vector<I> instances{{glm::mat4(1),{1,.8F,.6F,1}},{glm::mat4(1),{.2F,1,.2F,1}},{glm::mat4(1),{.8F,.2F,1,1}},{glm::mat4(1),{1,1,1,1}}};
#if defined(NADOC_TEST_INSTANCE_GROUPS) || defined(NADOC_TEST_INDEXED_MESH)
        for(unsigned j=4;j<17;++j){auto m=glm::translate(glm::mat4(1),glm::vec3(.005F*j,0,.008F*j));m[1][0]=.003F*j;instances.push_back({m,{.03F*j,.07F*float(j%7),.2F,trial>=24?.45F:1.F}});}
        if(trial>=24)for(auto& i:instances)i.color.a=.45F;
#endif
        instances[2].matrix=glm::translate(glm::mat4(1),glm::vec3(0,0,.25F)); // fully occluded by the first surface
        instances[3].matrix=glm::translate(glm::mat4(1),glm::vec3(.4F,.25F,-.2F));
        if(trial%4==3)instances[3].matrix=glm::scale(instances[3].matrix,glm::vec3(-.7F,.6F,1.2F));
#ifdef NADOC_TEST_INDEXED_MESH
        // Keep the first on/off shadow pair identical. Other trials cover the
        // exact small-count fallback, full groups and every interesting tail.
        const std::array<size_t,8> instanceCounts{17,17,1,7,8,9,24,25};
        const auto wanted=instanceCounts[trial%instanceCounts.size()];
        for(size_t j=instances.size();j<wanted;++j){auto m=glm::translate(glm::mat4(1),glm::vec3(-.006F*j,.004F*j,-.002F*j));m[0][1]=.002F*j;instances.push_back({m,{.03F*j,.4F,.2F,trial>=24?.45F:1.F}});}
        instances.resize(wanted);
#endif
        glBindBuffer(GL_ARRAY_BUFFER,vbo);glBufferData(GL_ARRAY_BUFFER,mesh.size()*sizeof(V),mesh.data(),GL_STREAM_DRAW);
        glBindBuffer(GL_ARRAY_BUFFER,ibo);glBufferData(GL_ARRAY_BUFFER,instances.size()*sizeof(I),instances.data(),GL_STREAM_DRAW);
        const auto world=glm::scale(glm::mat4(1),glm::vec3(.9F,.85F,1));const auto vp=world;const glm::mat4 light(1);
#ifdef NADOC_TEST_INSTANCE_GROUPS
        const auto expanded=nadoc_vr::view_groups::expand(mesh);glBindBuffer(GL_ARRAY_BUFFER,groupedVbo);glBufferData(GL_ARRAY_BUFFER,expanded.size()*sizeof(V),expanded.data(),GL_STREAM_DRAW);
        glActiveTexture(GL_TEXTURE9);glBindTexture(GL_TEXTURE_BUFFER,instanceTex);glTexBuffer(GL_TEXTURE_BUFFER,GL_RGBA32F,ibo);glActiveTexture(GL_TEXTURE1);
#endif
#ifdef NADOC_TEST_INDEXED_MESH
        const auto indexed=nadoc_vr::view_indexed::build(mesh);assert(indexed.plan.eligible);
        assert(indexed.indices.size()==mesh.size() && indexed.vertices.size()<mesh.size());
        glBindBuffer(GL_ARRAY_BUFFER,indexedVbo);glBufferData(GL_ARRAY_BUFFER,indexed.vertices.size()*sizeof(V),indexed.vertices.data(),GL_STREAM_DRAW);
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,indexBuffer);glBufferData(GL_ELEMENT_ARRAY_BUFFER,indexed.indices.size()*sizeof(uint32_t),indexed.indices.data(),GL_STREAM_DRAW);
        GLint maxTexels=0,vertexSamplers=0,textureUnits=0;glGetIntegerv(GL_MAX_TEXTURE_BUFFER_SIZE,&maxTexels);glGetIntegerv(GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS,&vertexSamplers);glGetIntegerv(GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS,&textureUnits);
        const auto groupPlan=nadoc_vr::view_indexed::planGroups(indexed.plan,instances.size(),sizeof(V),{uint64_t(maxTexels),vertexSamplers>0,textureUnits>9});
        const auto expanded=nadoc_vr::view_indexed::expandGroups(indexed.vertices,indexed.indices,groupPlan);
        assert(expanded.plan.eligible==(instances.size()>=8));
        if(expanded.plan.eligible){
            glBindBuffer(GL_ARRAY_BUFFER,groupedVbo);glBufferData(GL_ARRAY_BUFFER,expanded.vertices.size()*sizeof(V),expanded.vertices.data(),GL_STREAM_DRAW);
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,groupIndexBuffer);glBufferData(GL_ELEMENT_ARRAY_BUFFER,expanded.indices.size()*sizeof(uint32_t),expanded.indices.data(),GL_STREAM_DRAW);
            GLint vertexBytes=0,indexBytes=0;glGetBufferParameteriv(GL_ARRAY_BUFFER,GL_BUFFER_SIZE,&vertexBytes);glGetBufferParameteriv(GL_ELEMENT_ARRAY_BUFFER,GL_BUFFER_SIZE,&indexBytes);
            assert(nadoc_vr::view_indexed::groupResourcesComplete(expanded.plan,sizeof(V),vertexBytes,indexBytes));
            glActiveTexture(GL_TEXTURE9);glBindTexture(GL_TEXTURE_BUFFER,instanceTex);glTexBuffer(GL_TEXTURE_BUFFER,GL_RGBA32F,ibo);
            GLint texels=0,format=0;glGetTexLevelParameteriv(GL_TEXTURE_BUFFER,0,GL_TEXTURE_WIDTH,&texels);glGetTexLevelParameteriv(GL_TEXTURE_BUFFER,0,GL_TEXTURE_INTERNAL_FORMAT,&format);
            assert(size_t(texels)==instances.size()*5 && format==GL_RGBA32F);glActiveTexture(GL_TEXTURE1);
        }
#endif
        auto draw=[&](GLuint p,bool grouped=false,bool captureFeedback=false,bool shadowPass=false,bool indexedGroup=false) {
#ifdef NADOC_TEST_INDEXED_MESH
            assert(!indexedGroup || (expanded.plan.eligible && (trial<20 || trial>=24)));
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,indexedGroup?groupIndexBuffer:grouped?indexBuffer:0);
#else
            (void)indexedGroup;
#endif
            glBindBuffer(GL_ARRAY_BUFFER,
#ifdef NADOC_TEST_INDEXED_MESH
                indexedGroup?groupedVbo:
#endif
                grouped?
#ifdef NADOC_TEST_INSTANCE_GROUPS
                groupedVbo
#elif defined(NADOC_TEST_INDEXED_MESH)
                indexedVbo
#else
                vbo
#endif
                :vbo);
            glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,p));glVertexAttribPointer(1,4,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,color));glVertexAttribPointer(2,2,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,uv));glVertexAttribPointer(8,3,GL_FLOAT,GL_FALSE,sizeof(V),(void*)offsetof(V,normal));
            glUseProgram(p);glViewport(0,0,128,128);glDisable(GL_CULL_FACE);glDisable(GL_DITHER);glEnable(GL_DEPTH_TEST);glDepthMask(GL_TRUE);glDepthFunc(trial%4<2?GL_LESS:GL_LEQUAL);glEnable(GL_BLEND);glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
            glClearColor(.013F,.026F,.05F,1);glClearDepth(1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);const GLuint sentinel[4]={91,0,0,0};glClearBufferuiv(GL_COLOR,1,sentinel);
#ifdef NADOC_TEST_INDEXED_MESH
            glEnable(GL_STENCIL_TEST);glStencilMask(0xff);glClearStencil(13);glClear(GL_STENCIL_BUFFER_BIT);glStencilFunc(GL_ALWAYS,7,0xff);glStencilOp(GL_KEEP,GL_KEEP,GL_REPLACE);
#endif
            glUniformMatrix4fv(glGetUniformLocation(p,"vp"),1,GL_FALSE,&vp[0][0]);glUniformMatrix4fv(glGetUniformLocation(p,"worldModel"),1,GL_FALSE,&world[0][0]);
            glUniform1i(glGetUniformLocation(p,"instanced"),trial<20 || trial>=24);glUniform1i(glGetUniformLocation(p,"shadowPass"),shadowPass);glUniform1i(glGetUniformLocation(p,"uFrostEnabled"),0);
            glUniform1i(glGetUniformLocation(p,"atlas"),1);glUniform1i(glGetUniformLocation(p,"uMenuBackdrop"),7);glUniform1i(glGetUniformLocation(p,"uMenuDepth"),8);glUniform1i(glGetUniformLocation(p,"uShadowMap"),0);
            glUniform1i(glGetUniformLocation(p,"uShadowsEnabled"),trial%2);glUniformMatrix4fv(glGetUniformLocation(p,"uLightViewProjection"),1,GL_FALSE,&light[0][0]);glUniform3f(glGetUniformLocation(p,"uLightDirection"),0,0,1);
#ifdef NADOC_TEST_INDEXED_MESH
            if(captureFeedback){glBindBuffer(GL_TRANSFORM_FEEDBACK_BUFFER,feedback);glBufferData(GL_TRANSFORM_FEEDBACK_BUFFER,mesh.size()*(trial<20 || trial>=24?instances.size():1)*22*sizeof(uint32_t),nullptr,GL_STREAM_READ);glBindBufferBase(GL_TRANSFORM_FEEDBACK_BUFFER,0,feedback);glEnable(GL_RASTERIZER_DISCARD);glBeginTransformFeedback(GL_TRIANGLES);}
            if(indexedGroup){glUniform1i(glGetUniformLocation(p,"uGroupedInstances"),9);glUniform1i(glGetUniformLocation(p,"uGroupBaseVertices"),int(indexed.vertices.size()));for(auto call:nadoc_vr::view_indexed::groupDraws(indexed.indices.size(),instances.size()))if(call.instances){glUniform1i(glGetUniformLocation(p,"uGroupFirstInstance"),call.firstInstance);glDrawElementsInstanced(GL_TRIANGLES,call.indexCount,GL_UNSIGNED_INT,nullptr,call.instances);}}
            else if(grouped)glDrawElementsInstanced(GL_TRIANGLES,indexed.indices.size(),GL_UNSIGNED_INT,nullptr,trial<20 || trial>=24?instances.size():1);
            else
#elif defined(NADOC_TEST_INSTANCE_GROUPS)
            if(captureFeedback){glBindBuffer(GL_TRANSFORM_FEEDBACK_BUFFER,feedback);glBufferData(GL_TRANSFORM_FEEDBACK_BUFFER,mesh.size()*instances.size()*13*sizeof(float),nullptr,GL_STREAM_READ);glBindBufferBase(GL_TRANSFORM_FEEDBACK_BUFFER,0,feedback);glEnable(GL_RASTERIZER_DISCARD);glBeginTransformFeedback(GL_TRIANGLES);}
            if(grouped){glUniform1i(glGetUniformLocation(p,"uGroupedInstances"),9);glUniform1i(glGetUniformLocation(p,"uGroupBaseVertices"),int(mesh.size()));for(auto call:nadoc_vr::view_groups::draws(mesh.size(),instances.size()))if(call.instances){glUniform1i(glGetUniformLocation(p,"uGroupFirstInstance"),call.firstInstance);glDrawArraysInstanced(GL_TRIANGLES,0,call.vertices,call.instances);}}
            else
#else
            (void)captureFeedback;
#endif
            glDrawArraysInstanced(GL_TRIANGLES,0,mesh.size(),trial<20 || trial>=24?instances.size():1);
#if defined(NADOC_TEST_INSTANCE_GROUPS) || defined(NADOC_TEST_INDEXED_MESH)
            if(captureFeedback){glEndTransformFeedback();glDisable(GL_RASTERIZER_DISCARD);}
#endif
            Pixels out;out.color.resize(128*128*4);out.depth.resize(128*128);out.ids.resize(128*128);
            glReadBuffer(GL_COLOR_ATTACHMENT0);glReadPixels(0,0,128,128,GL_RGBA,GL_UNSIGNED_BYTE,out.color.data());glReadPixels(0,0,128,128,GL_DEPTH_COMPONENT,GL_FLOAT,out.depth.data());
            glReadBuffer(GL_COLOR_ATTACHMENT1);glReadPixels(0,0,128,128,GL_RED_INTEGER,GL_UNSIGNED_INT,out.ids.data());
#ifdef NADOC_TEST_INDEXED_MESH
            out.stencil.resize(128*128);glReadPixels(0,0,128,128,GL_STENCIL_INDEX,GL_UNSIGNED_BYTE,out.stencil.data());
#endif
            assert(glGetError()==GL_NO_ERROR);return out;
        };
        const auto before=draw(legacy),after=draw(trial<24?opaque:legacy);
        assert(before.color==after.color);assert(before.depth==after.depth);assert(before.ids==after.ids);
#ifdef NADOC_TEST_INSTANCE_GROUPS
        if(trial<20 || trial>=24){
            const auto grouped=draw(groupLegacy,true);assert(before.color==grouped.color && before.depth==grouped.depth && before.ids==grouped.ids);
            if(trial<24){const auto both=draw(groupOpaque,true);assert(before.color==both.color && before.depth==both.depth && before.ids==both.ids);}
            auto captured=[&](GLuint p,bool g){draw(p,g,true);std::vector<float> data(mesh.size()*instances.size()*13);glBindBuffer(GL_TRANSFORM_FEEDBACK_BUFFER,feedback);glGetBufferSubData(GL_TRANSFORM_FEEDBACK_BUFFER,0,data.size()*sizeof(float),data.data());assert(glGetError()==GL_NO_ERROR);return data;};
            const auto a=captured(legacy,false),b=captured(groupLegacy,true);assert(a==b);feedbackCompared+=mesh.size()*instances.size();
        }
#endif
#ifdef NADOC_TEST_INDEXED_MESH
        const auto indexedLegacy=draw(legacy,true);assert(samePixels(before,indexedLegacy));
        ++indexedCompared;
        if(trial<24){const auto indexedOpaque=draw(opaque,true);assert(samePixels(after,indexedOpaque));++indexedCompared;}
        // The actual legacy shadowPass branch must preserve geometry, depth,
        // stencil and IDs too, including its zero-normal discard rule.
        const auto shadowBefore=draw(legacy,false,false,true),shadowAfter=draw(legacy,true,false,true);
        assert(samePixels(shadowBefore,shadowAfter));++indexedCompared;
        for(size_t pixel=0;pixel<shadowAfter.depth.size();++pixel)if(shadowAfter.depth[pixel]<1){assert(shadowAfter.stencil[pixel]==7 && shadowAfter.ids[pixel]==0);++shadowCovered;}
        auto captured=[&](GLuint p,bool useIndex,bool useGroup=false){
            draw(p,useIndex,true,false,useGroup);std::vector<uint32_t> data(mesh.size()*(trial<20 || trial>=24?instances.size():1)*22);
            glBindBuffer(GL_TRANSFORM_FEEDBACK_BUFFER,feedback);glGetBufferSubData(GL_TRANSFORM_FEEDBACK_BUFFER,0,data.size()*sizeof(uint32_t),data.data());assert(glGetError()==GL_NO_ERROR);return data;
        };
        const auto originalVertices=captured(legacy,false),indexedVertices=captured(legacy,true);
        assert(originalVertices==indexedVertices);feedbackCompared+=originalVertices.size()/22;
        if(expanded.plan.eligible && (trial<20 || trial>=24)){
            const auto groupedLegacy=draw(groupLegacy,true,false,false,true);assert(samePixels(before,groupedLegacy));++groupedCompared;
            if(trial<24){const auto groupedOpaque=draw(groupOpaque,true,false,false,true);assert(samePixels(after,groupedOpaque));++groupedCompared;}
            const auto groupedVertices=captured(groupLegacy,true,true);assert(originalVertices==groupedVertices);groupedFeedbackCompared+=groupedVertices.size()/22;
        }else{
            // Production keeps the ordinary indexed path for small counts and
            // noninstanced/shadow draws. Switch away from the previous grouped
            // EBO/TBO and prove the fallback still produces the original image.
            const auto fallback=draw(legacy,true);assert(samePixels(before,fallback));++groupFallbackCompared;
        }
        for(size_t pixel=0;pixel<indexedLegacy.depth.size();++pixel)assert(indexedLegacy.stencil[pixel]==(indexedLegacy.depth[pixel]<1?7:13));
#endif
        for(size_t pixel=0;pixel<after.depth.size();++pixel)if(after.depth[pixel]<1){assert(after.ids[pixel]==0);++covered;}
        if(trial==0)noShadow=before.color;
        if(trial==1)for(size_t i=0;i<before.color.size();++i)shadowChanged+=noShadow[i]!=before.color[i];
        ++compared;
    }
    assert(covered>100000 && shadowChanged>1000);
    std::cout<<"Opaque GL exact comparison cases="<<compared<<" covered_pixel_cases="<<covered<<" equal_color_depth_ids=true shadow_sensitive_channels="<<shadowChanged<<"\n";
#ifdef NADOC_TEST_INSTANCE_GROUPS
    std::cout<<"Grouped exact ordered transform-feedback vertices="<<feedbackCompared<<" plus opaque/translucent overlapping pixel equality passed\n";
    glDeleteProgram(groupLegacy);glDeleteProgram(groupOpaque);glDeleteBuffers(1,&groupedVbo);glDeleteBuffers(1,&feedback);glDeleteTextures(1,&instanceTex);
#endif
#ifdef NADOC_TEST_INDEXED_MESH
    assert(indexedCompared==88 && shadowCovered>100000 && feedbackCompared>0);
    std::cout<<"Indexed GL exact comparisons="<<indexedCompared<<" color_depth_stencil_ids_equal=true ordered_vertex_records="<<feedbackCompared<<" shadow_covered_pixel_cases="<<shadowCovered<<" mesh_sizes=75,420 opaque_translucent_shadow_pass=true\n";
    assert(groupedCompared>24 && groupedFeedbackCompared>0 && groupFallbackCompared>0);
    std::cout<<"Grouped indexed GL exact comparisons="<<groupedCompared<<" fallback_comparisons="<<groupFallbackCompared<<" ordered_vertex_records="<<groupedFeedbackCompared<<" instance_counts=1,7,8,9,17,24,25 actual_sphere_unique_vertices=91\n";
    glDeleteBuffers(1,&indexedVbo);glDeleteBuffers(1,&indexBuffer);glDeleteBuffers(1,&feedback);
    glDeleteProgram(groupLegacy);glDeleteProgram(groupOpaque);glDeleteBuffers(1,&groupedVbo);glDeleteBuffers(1,&groupIndexBuffer);glDeleteTextures(1,&instanceTex);
#endif
    glDeleteTextures(3,outputs.data());glDeleteTextures(1,&shadow);glDeleteTextures(1,&atlas);glDeleteFramebuffers(1,&framebuffer);glDeleteBuffers(1,&vbo);glDeleteBuffers(1,&ibo);glDeleteVertexArrays(1,&vao);glDeleteProgram(legacy);glDeleteProgram(opaque);glfwDestroyWindow(window);glfwTerminate();
}
