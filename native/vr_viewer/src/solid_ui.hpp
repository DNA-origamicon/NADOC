#pragma once
#include "thumbwheel_mesh.hpp"
// Included after the native Vertex and shader helpers. Shared by the native
// headset and the standalone GLFW desktop evaluator; no browser imitation.
class SolidUi {
 public:
    std::vector<Vertex> vertices;
    void triangle(glm::vec3 a,glm::vec3 b,glm::vec3 c,glm::vec3 color) {
        for(auto p:{a,b,c})vertices.push_back({p,color,1.F});
    }
    void rect(float x,float y,float w,float h,glm::vec3 color,float z=.004F) {
        const glm::vec3 a{x,y,z},b{x+w,y,z},c{x+w,y+h,z},d{x,y+h,z};
        triangle(a,b,c,color);triangle(a,c,d,color);
    }
    void text(const std::string& label,float x,float y,float scale,glm::vec3 color,float z=.008F) {
        for(size_t i=0;i<label.size();++i) {
            const auto rows=nadoc_vr::glyph(static_cast<char>(std::toupper(static_cast<unsigned char>(label[i]))));
            for(size_t row=0;row<rows.size();++row)for(int col=0;col<5;++col)
                if(rows[row]&(1U<<(4-col)))rect(x+(i*6+col)*scale,y-row*scale,scale*.82F,scale*.82F,color,z);
        }
    }
    static std::vector<glm::vec3> contour(float x,float y,float w,float h,float r,float z) {
        r=std::clamp(r,0.F,std::min(w,h)*.5F);
        std::vector<glm::vec3> points;
        for(int corner=0;corner<4;++corner)for(int n=0;n<=10;++n) {
            const float a=(corner+n/10.F)*glm::half_pi<float>();
            points.push_back({(corner==0||corner==3?x+w-r:x+r)+r*std::cos(a),
                              (corner<2?y+h-r:y+r)+r*std::sin(a),z});
        }
        return points;
    }
    void rounded(float x,float y,float w,float h,float r,glm::vec3 color,float z) {
        const auto ring=contour(x,y,w,h,r,z);
        for(size_t i=0;i<ring.size();++i)triangle({x+w*.5F,y+h*.5F,z},ring[i],ring[(i+1)%ring.size()],color);
    }
    void bevel(float x,float y,float w,float h,float r,float back,float front,float inset,glm::vec3 color) {
        const auto a=contour(x,y,w,h,r,back),b=contour(x+inset,y+inset,w-2*inset,h-2*inset,std::max(0.F,r-inset),front);
        for(size_t i=0;i<a.size();++i) {
            const size_t j=(i+1)%a.size();const auto cross=glm::cross(a[j]-a[i],b[j]-a[i]);
            const float light=glm::length(cross)<1e-9F?.6F:.42F+.48F*std::max(0.F,glm::dot(glm::normalize(cross),glm::normalize(glm::vec3(-.4F,.7F,1.F))));
            triangle(a[i],a[j],b[j],color*light);triangle(a[i],b[j],b[i],color*light);
        }
        rounded(x+inset,y+inset,w-2*inset,h-2*inset,std::max(0.F,r-inset),color,front);
    }
    template<class Transform> void wheel(const nadoc_vr::ThumbwheelShape& shape,float phase,
            glm::vec3 center,glm::vec3 color,Transform transform) {
        nadoc_vr::thumbwheelMesh(shape,phase,center,[&](auto a,auto b,auto c,auto normal) {
            const float light=.32F+.68F*std::max(0.F,glm::dot(normal,glm::normalize(glm::vec3(-.4F,.7F,1.F))));
            triangle(transform(a),transform(b),transform(c),color*light);
        });
    }
    void render(const glm::mat4& vp) {
        if(vertices.empty())return;
        if(!program_) {
            program_=makeProgram();glGenVertexArrays(1,&vao_);glGenBuffers(1,&vbo_);
            glBindVertexArray(vao_);glBindBuffer(GL_ARRAY_BUFFER,vbo_);
            glEnableVertexAttribArray(0);glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),reinterpret_cast<void*>(offsetof(Vertex,position)));
            glEnableVertexAttribArray(1);glVertexAttribPointer(1,3,GL_FLOAT,GL_FALSE,sizeof(Vertex),reinterpret_cast<void*>(offsetof(Vertex,color)));
        }
        glEnable(GL_DEPTH_TEST);glDepthMask(GL_TRUE);glDisable(GL_BLEND);
        const auto cull=glIsEnabled(GL_CULL_FACE);glDisable(GL_CULL_FACE);
        glUseProgram(program_);glUniform1i(glGetUniformLocation(program_,"uVolumeCount"),0);
        glUniform1f(glGetUniformLocation(program_,"uVolumeOpacity"),1);
        glUniformMatrix4fv(glGetUniformLocation(program_,"uViewProjection"),1,GL_FALSE,&vp[0][0]);
        glBindVertexArray(vao_);glBindBuffer(GL_ARRAY_BUFFER,vbo_);
        glBufferData(GL_ARRAY_BUFFER,vertices.size()*sizeof(Vertex),vertices.data(),GL_DYNAMIC_DRAW);
        glDrawArrays(GL_TRIANGLES,0,vertices.size());glBindVertexArray(0);glUseProgram(0);
        if(cull)glEnable(GL_CULL_FACE);
    }
    void shutdown() {
        if(vbo_)glDeleteBuffers(1,&vbo_);
        if(vao_)glDeleteVertexArrays(1,&vao_);
        if(program_)glDeleteProgram(program_);
        vbo_=vao_=program_=0;
    }
 private:
    GLuint program_=0,vao_=0,vbo_=0;
};
