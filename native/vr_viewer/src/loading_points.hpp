#pragma once
// Borrow the displayed instance buffers: no geometry copies, uploads, or style
// changes when the loading frame guard activates. IDs remain those of the model.
class LoadingPoints {
    GLuint program_=0,vao_=0;
 public:
    LoadingPoints(){
        const auto vertex=compileShader(GL_VERTEX_SHADER,R"GLSL(
            #version 330 core
            layout(location=0) in vec3 position;
            layout(location=1) in vec3 color;
            layout(location=2) in uint objectId;
            uniform mat4 vp,model;
            out vec3 vWorldPosition;
            out vec3 vColor;
            flat out uint vId;
            void main(){
                vWorldPosition=(model*vec4(position,1)).xyz;
                gl_Position=vp*vec4(vWorldPosition,1);
                gl_PointSize=3.0;
                vColor=color;vId=objectId;
            }
        )GLSL");
        const auto fragment=compileShader(GL_FRAGMENT_SHADER,nadoc_vr::volumeFragment(R"GLSL(
            #version 330 core
            in vec3 vWorldPosition;
            in vec3 vColor;
            flat in uint vId;
            layout(location=0) out vec4 outColor;
            layout(location=1) out uint outId;
            void main() {
                outColor=vec4(vColor,1);outId=vId;
            }
        )GLSL","void main() {","vWorldPosition").c_str());
        program_=glCreateProgram();glAttachShader(program_,vertex);glAttachShader(program_,fragment);
        glLinkProgram(program_);glDeleteShader(vertex);glDeleteShader(fragment);
        GLint ok=0;glGetProgramiv(program_,GL_LINK_STATUS,&ok);
        if(!ok){glDeleteProgram(program_);throw std::runtime_error("Cannot link loading point shader");}
        glGenVertexArrays(1,&vao_);
    }
    LoadingPoints(const LoadingPoints&)=delete;
    LoadingPoints& operator=(const LoadingPoints&)=delete;
    ~LoadingPoints(){glDeleteVertexArrays(1,&vao_);glDeleteProgram(program_);}
    GLuint program()const{return program_;}
    void begin(const glm::mat4& vp,const glm::mat4& model,bool ids)const{
        glUseProgram(program_);
        glUniformMatrix4fv(glGetUniformLocation(program_,"vp"),1,GL_FALSE,&vp[0][0]);
        glUniformMatrix4fv(glGetUniformLocation(program_,"model"),1,GL_FALSE,&model[0][0]);
        glBindVertexArray(vao_);glPointSize(3);
        if(ids){const GLenum buffers[]={GL_COLOR_ATTACHMENT0,GL_COLOR_ATTACHMENT1};glDrawBuffers(2,buffers);}
    }
    template<class T> void draw(GLuint buffer,GLsizei count,size_t position)const{
        if(!count)return;
        glBindBuffer(GL_ARRAY_BUFFER,buffer);
        glEnableVertexAttribArray(0);glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,sizeof(T),reinterpret_cast<void*>(position));
        glEnableVertexAttribArray(1);glVertexAttribPointer(1,3,GL_FLOAT,GL_FALSE,sizeof(T),reinterpret_cast<void*>(offsetof(T,color)));
        glEnableVertexAttribArray(2);glVertexAttribIPointer(2,1,GL_UNSIGNED_INT,sizeof(T),reinterpret_cast<void*>(offsetof(T,objectId)));
        glDrawArrays(GL_POINTS,0,count);
    }
    void end(bool ids)const{
        if(ids)glDrawBuffer(GL_COLOR_ATTACHMENT0);
        glPointSize(1);glBindVertexArray(0);glUseProgram(0);
    }
};
