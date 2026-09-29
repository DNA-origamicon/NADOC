#pragma once

// SteamVR's calibrated OpenXR STAGE is independent of molecular/model transforms.
class RoomFloor {
 public:
    XrSpace stage=XR_NULL_HANDLE;
    XrExtent2Df area{};
    glm::mat4 stageToLocal{1};
    bool located=false,bounded=false;
    GLuint program=0,vao=0;
    void initialize(XrSession session) {
        XrReferenceSpaceCreateInfo info{XR_TYPE_REFERENCE_SPACE_CREATE_INFO};
        info.referenceSpaceType=XR_REFERENCE_SPACE_TYPE_STAGE;
        info.poseInReferenceSpace.orientation.w=1;
        xrCreateReferenceSpace(session,&info,&stage);
        const auto vs=compileShader(GL_VERTEX_SHADER,R"(#version 330 core
uniform mat4 vp;uniform mat4 stageToLocal;out vec2 floorPoint;
void main(){vec2 p=vec2((gl_VertexID==1||gl_VertexID==2)?12:-12,gl_VertexID>=2?12:-12);floorPoint=p;gl_Position=vp*stageToLocal*vec4(p.x,0.002,p.y,1);})");
        const auto fs=compileShader(GL_FRAGMENT_SHADER,R"(#version 330 core
in vec2 floorPoint;uniform vec2 area;uniform bool bounded;layout(location=0) out vec4 color;layout(location=1) out uint objectId;
float grid(float spacing){vec2 q=floorPoint/spacing;vec2 d=abs(fract(q-0.5)-0.5)/max(fwidth(q),vec2(0.0001));return 1.0-min(min(d.x,d.y),1.0);}
void main(){objectId=0u;float fade=1.0-smoothstep(3.0,10.0,length(floorPoint));float minor=grid(0.5),major=grid(1.0);float alpha=(minor*0.16+major*0.18)*fade;
vec3 rgb=vec3(0.43,0.48,0.52);
if(bounded){vec2 d=abs(abs(floorPoint)-area*0.5);vec2 aa=max(fwidth(floorPoint),vec2(0.001));float edge=max((1.0-smoothstep(0.012,0.012+aa.x,d.x))*step(abs(floorPoint.y),area.y*0.5+0.015),(1.0-smoothstep(0.012,0.012+aa.y,d.y))*step(abs(floorPoint.x),area.x*0.5+0.015));rgb=mix(rgb,vec3(0.18,0.76,0.84),edge);alpha=max(alpha,edge*0.9);}
if(alpha<0.008)discard;color=vec4(rgb,alpha);})");
        program=glCreateProgram();glAttachShader(program,vs);glAttachShader(program,fs);glLinkProgram(program);
        glDeleteShader(vs);glDeleteShader(fs);
        GLint ok=0;glGetProgramiv(program,GL_LINK_STATUS,&ok);if(!ok)throw std::runtime_error("Floor shader link failed");
        glGenVertexArrays(1,&vao);
    }
    void update(XrSession session,XrSpace local,XrTime time) {
        located=false;bounded=false;
        if(stage==XR_NULL_HANDLE)return;
        XrSpaceLocation pose{XR_TYPE_SPACE_LOCATION};
        if(XR_FAILED(xrLocateSpace(stage,local,time,&pose)))return;
        const auto required=XR_SPACE_LOCATION_POSITION_VALID_BIT|XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;
        if((pose.locationFlags&required)!=required)return;
        const auto& p=pose.pose.position;const auto& q=pose.pose.orientation;
        stageToLocal=glm::translate(glm::mat4(1),glm::vec3(p.x,p.y,p.z))*glm::toMat4(glm::quat(q.w,q.x,q.y,q.z));
        located=true;
        bounded=xrGetReferenceSpaceBoundsRect(session,XR_REFERENCE_SPACE_TYPE_STAGE,&area)==XR_SUCCESS && area.width>0 && area.height>0;
    }
    void render(const glm::mat4& vp) const {
        if(!located)return;
        glUseProgram(program);glUniformMatrix4fv(glGetUniformLocation(program,"vp"),1,GL_FALSE,&vp[0][0]);
        glUniformMatrix4fv(glGetUniformLocation(program,"stageToLocal"),1,GL_FALSE,&stageToLocal[0][0]);
        glUniform2f(glGetUniformLocation(program,"area"),area.width,area.height);glUniform1i(glGetUniformLocation(program,"bounded"),bounded);
        glEnable(GL_DEPTH_TEST);glDepthMask(GL_FALSE);glDisable(GL_CULL_FACE);
        glEnable(GL_BLEND);glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA);
        glBindVertexArray(vao);glDrawArrays(GL_TRIANGLE_FAN,0,4);glBindVertexArray(0);
        glDisable(GL_BLEND);glDepthMask(GL_TRUE);glUseProgram(0);
    }
    std::string json() const {
        std::ostringstream out;out<<"{\"located\":"<<(located?"true":"false")<<",\"bounded\":"<<(bounded?"true":"false")<<",\"source\":\"OpenXR STAGE\",\"grid_spacing_m\":0.5,\"width_m\":"<<area.width<<",\"depth_m\":"<<area.height<<",\"stage_to_local\":[";
        for(int row=0;row<4;++row){if(row)out<<',';out<<'[';for(int col=0;col<4;++col){if(col)out<<',';out<<stageToLocal[col][row];}out<<']';}out<<"]}";return out.str();
    }
    void shutdown() {
        if(stage!=XR_NULL_HANDLE)xrDestroySpace(stage);
        if(program)glDeleteProgram(program);
        if(vao)glDeleteVertexArrays(1,&vao);
        stage=XR_NULL_HANDLE;program=vao=0;
    }
};
