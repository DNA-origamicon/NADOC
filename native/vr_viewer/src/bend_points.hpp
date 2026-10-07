#pragma once
// Shared Bend, Twist and Move spatial guide; deformation and boundary
// primitives approximate the authoritative backend geometry.
// Borrow resident instance positions. Cache a bounded index list only when the
// selection/style changes; dragging and stereo rendering upload uniforms only.
class BendPoints {
    GLuint program_=0,vao_=0;
    std::array<GLuint,4> buffers_{};
    std::array<GLsizei,4> counts_{};
 public:
    static constexpr size_t channelLimit=8192;
    bool dirty=true;
    static std::vector<GLuint> selectedIndices(const std::vector<unsigned char>& mask) {
        const size_t selected=std::count(mask.begin(),mask.end(),2);
        const size_t count=std::min(selected,channelLimit);
        std::vector<GLuint> result;result.reserve(count);
        size_t ordinal=0,next=0;
        for(size_t i=0;i<mask.size() && result.size()<count;++i)if(mask[i]==2) {
            if(ordinal==next) {
                result.push_back(GLuint(i));
                next=result.size()*selected/count;
            }
            ++ordinal;
        }
        return result;
    }
    BendPoints() {
        const auto vertex=compileShader(GL_VERTEX_SHADER,R"GLSL(
            #version 330 core
            layout(location=0) in vec3 position;
            uniform mat4 vp,model,rigid;
            uniform int mode;
            uniform vec3 anchor,tangent,direction;
            uniform float contour,angle,side;
            out vec3 vWorldPosition;
            void main() {
                vec3 bent;
                if(mode==2) bent=(rigid*vec4(position,1)).xyz;
                else {
                    vec3 delta=position-anchor;
                    float axial=dot(delta,tangent);
                    vec3 transverse=delta-tangent*axial;
                    if(mode==1) {
                        // Plane 1 stays fixed; beyond plane 2 retain the total spin.
                        float phase=angle*clamp(axial/contour,0.0,1.0);
                        bent=anchor+tangent*axial+transverse*cos(phase)
                            +cross(tangent,transverse)*sin(phase);
                    } else {
                        float distance=side*axial;
                        float along=clamp(distance,0.0,contour);
                        float phase=angle*along/contour;
                        float s=sin(phase),c=cos(phase);
                        vec3 binormal=cross(tangent,direction);
                        vec3 rotated=transverse*c+cross(binormal,transverse)*s
                            +binormal*dot(binormal,transverse)*(1.0-c);
                        // 2*sin(x/2)^2 avoids cancellation close to zero curvature.
                        vec3 arc=angle<0.00001?tangent*along:
                            (tangent*s+direction*(2.0*pow(sin(phase*0.5),2.0)))*(contour/angle);
                        vec3 tail=(distance-along)*(tangent*c+direction*s);
                        bent=anchor+side*(arc+tail)+rotated;
                    }
                }
                vWorldPosition=(model*vec4(bent,1)).xyz;
                gl_Position=vp*vec4(vWorldPosition,1);
                gl_PointSize=3.0;
            }
        )GLSL");
        const auto fragment=compileShader(GL_FRAGMENT_SHADER,nadoc_vr::volumeFragment(R"GLSL(
            #version 330 core
            in vec3 vWorldPosition;
            layout(location=0) out vec4 outColor;
            layout(location=1) out uint outId;
            void main() {
                outColor=vec4(0.25,1.0,0.8,1.0);
                // A guide must not impersonate editable molecular geometry.
                outId=0u;
            }
        )GLSL","void main() {","vWorldPosition").c_str());
        program_=glCreateProgram();glAttachShader(program_,vertex);glAttachShader(program_,fragment);
        glLinkProgram(program_);glDeleteShader(vertex);glDeleteShader(fragment);
        GLint ok=0;glGetProgramiv(program_,GL_LINK_STATUS,&ok);
        if(!ok){glDeleteProgram(program_);throw std::runtime_error("Cannot link bend point shader");}
        glGenVertexArrays(1,&vao_);glGenBuffers(4,buffers_.data());
    }
    BendPoints(const BendPoints&)=delete;
    BendPoints& operator=(const BendPoints&)=delete;
    ~BendPoints(){glDeleteBuffers(4,buffers_.data());glDeleteVertexArrays(1,&vao_);glDeleteProgram(program_);}
    GLuint program()const{return program_;}
    size_t pointCount()const{return counts_[0]+2*counts_[1]+2*counts_[2]+counts_[3];}
    void update(const std::array<std::vector<unsigned char>,4>& masks) {
        if(!dirty)return;
        glBindVertexArray(vao_);
        for(size_t i=0;i<4;++i) {
            const auto indices=selectedIndices(masks[i]);counts_[i]=GLsizei(indices.size());
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,buffers_[i]);
            glBufferData(GL_ELEMENT_ARRAY_BUFFER,indices.size()*sizeof(GLuint),indices.data(),GL_STATIC_DRAW);
        }
        glBindVertexArray(0);dirty=false;
    }
    void begin(const glm::mat4& vp,const glm::mat4& model,const nadoc_vr::BendArc& arc,int mode=0,const glm::mat4& rigid=glm::mat4(1))const {
        glUseProgram(program_);glBindVertexArray(vao_);glPointSize(3);
        glUniformMatrix4fv(glGetUniformLocation(program_,"vp"),1,GL_FALSE,&vp[0][0]);
        glUniformMatrix4fv(glGetUniformLocation(program_,"model"),1,GL_FALSE,&model[0][0]);
        glUniform1i(glGetUniformLocation(program_,"mode"),mode);
        glUniformMatrix4fv(glGetUniformLocation(program_,"rigid"),1,GL_FALSE,&rigid[0][0]);
        const auto anchor=mode==1 || arc.fixedEnd==0?arc.a:arc.b;
        glUniform3fv(glGetUniformLocation(program_,"anchor"),1,&anchor[0]);
        glUniform3fv(glGetUniformLocation(program_,"tangent"),1,&arc.tangent[0]);
        glUniform3fv(glGetUniformLocation(program_,"direction"),1,&arc.direction[0]);
        glUniform1f(glGetUniformLocation(program_,"contour"),arc.length);
        glUniform1f(glGetUniformLocation(program_,"angle"),arc.angle);
        glUniform1f(glGetUniformLocation(program_,"side"),arc.fixedEnd==0?1.F:-1.F);
    }
    template<class T> void draw(size_t channel,GLuint buffer,size_t offset)const {
        if(!counts_[channel])return;
        glBindBuffer(GL_ARRAY_BUFFER,buffer);glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,buffers_[channel]);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(T),reinterpret_cast<void*>(offset));
        glDrawElements(GL_POINTS,counts_[channel],GL_UNSIGNED_INT,nullptr);
    }
    void end()const {glPointSize(1);glBindVertexArray(0);glUseProgram(0);}
};
