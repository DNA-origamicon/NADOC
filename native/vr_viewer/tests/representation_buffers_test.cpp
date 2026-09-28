#define GL_GLEXT_PROTOTYPES
#include "representation_buffers.hpp"
#include <GLFW/glfw3.h>
#include <stdexcept>
#include <iostream>
int main() {
    auto check=[](bool value){if(!value)throw std::runtime_error("GPU representation cache invariant failed");};
    if(!glfwInit())return 77;
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3);glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,3);
    auto* window=glfwCreateWindow(32,32,"buffer cache test",nullptr,nullptr);
    if(!window){glfwTerminate();return 77;}
    glfwMakeContextCurrent(window);
    {
        nadoc_vr::RepresentationBuffers cache;
        std::array<GLuint,4> buffers{};glGenBuffers(4,buffers.data());
        const std::array<int,3> original{17,23,42}, changed{0,0,0};
        for(auto buffer:buffers){glBindBuffer(GL_ARRAY_BUFFER,buffer);glBufferData(GL_ARRAY_BUFFER,sizeof(original),original.data(),GL_DYNAMIC_DRAW);}
        cache.capture(1,2,buffers,{3,4,5,6},{1,2,3},4);
        for(auto buffer:buffers){glBindBuffer(GL_ARRAY_BUFFER,buffer);glBufferData(GL_ARRAY_BUFFER,sizeof(changed),changed.data(),GL_DYNAMIC_DRAW);}
        std::array<GLsizei,4> counts{};glm::vec3 center{};float radius=0;
        check(!cache.restore(1,3,buffers,counts,center,radius));
        check(!cache.restore(0,2,buffers,counts,center,radius));
        check(cache.restore(1,2,buffers,counts,center,radius));
        check(counts==std::array<GLsizei,4>{3,4,5,6} && center==glm::vec3(1,2,3) && radius==4);
        for(auto buffer:buffers){std::array<int,3> actual{};glBindBuffer(GL_ARRAY_BUFFER,buffer);glGetBufferSubData(GL_ARRAY_BUFFER,0,sizeof(actual),actual.data());check(actual==original);}
        cache.clear();check(!cache.restore(1,2,buffers,counts,center,radius));
        check(glGetError()==GL_NO_ERROR);glDeleteBuffers(4,buffers.data());
    }
    glfwDestroyWindow(window);glfwTerminate();std::cout<<"GPU bytes, metadata, color keys and invalidation passed\n";
}
