#pragma once

// One background snapshot per eye/view, shared by all native menu surfaces.
// Sample only the scene already rendered into this view, never the other eye.
inline constexpr const char* frostedGlassShader = R"GLSL(
uniform sampler2D uMenuBackdrop;
uniform vec4 uBackdropViewport;
uniform bool uFrostEnabled;
vec4 frostedMenu(vec4 ink) {
    if (!uFrostEnabled) return ink;
    vec2 uv = (gl_FragCoord.xy-uBackdropViewport.xy)/uBackdropViewport.zw;
    vec2 stepUV = 7.5/uBackdropViewport.zw;
    vec3 blurred = vec3(0);
    float total = 0.0;
    for (int y=-2;y<=2;y++) for (int x=-2;x<=2;x++) {
        float weight = exp(-float(x*x+y*y)/3.0);
        blurred += textureLod(uMenuBackdrop,clamp(uv+vec2(x,y)*stepUV,vec2(0),vec2(1)),1.0).rgb*weight;
        total += weight;
    }
    vec3 glass = mix(blurred/total,vec3(0.90,0.92,0.94),0.10);
    float high = max(ink.r,max(ink.g,ink.b));
    float low = min(ink.r,min(ink.g,ink.b));
    // Low-valued colored fills encode subtle button tints. Neutral panel fills
    // retain only a trace of white. Foreground colors are not remapped.
    vec3 tint = ink.rgb-vec3((high+low)*0.5);
    glass += high>0.095 ? tint*0.65 : vec3(0);
    float foreground = smoothstep(0.20,0.48,high);
    // Keep the desktop icon RGB/gradient stops and light lettering intact.
    return vec4(mix(glass,ink.rgb,foreground),ink.a);
}
)GLSL";

class FrostedGlass {
 public:
    inline static GLuint backdrop=0;
    inline static GLint viewport[4]={0,0,1,1};
    inline static bool available=false;
    GLuint framebuffer=0;
    int width=0,height=0;
    void capture() {
        GLint draw=0,read=0,readBuffer=0,texture=0;
        glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING,&draw);
        glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING,&read);
        glGetIntegerv(GL_READ_BUFFER,&readBuffer);
        glGetIntegerv(GL_VIEWPORT,viewport);
        glGetIntegerv(GL_TEXTURE_BINDING_2D,&texture);
        if(!backdrop)glGenTextures(1,&backdrop);
        if(!framebuffer)glGenFramebuffers(1,&framebuffer);
        glBindTexture(GL_TEXTURE_2D,backdrop);
        const int w=std::max(1,viewport[2]/2),h=std::max(1,viewport[3]/2);
        if(width!=w||height!=h) {
            width=w;height=h;
            glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,w,h,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR_MIPMAP_LINEAR);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
        }
        glBindFramebuffer(GL_READ_FRAMEBUFFER,draw);
        glReadBuffer(draw?GL_COLOR_ATTACHMENT0:GL_BACK);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER,framebuffer);
        glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,backdrop,0);
        glDrawBuffer(GL_COLOR_ATTACHMENT0);
        glBlitFramebuffer(viewport[0],viewport[1],viewport[0]+viewport[2],viewport[1]+viewport[3],0,0,w,h,GL_COLOR_BUFFER_BIT,GL_LINEAR);
        glGenerateMipmap(GL_TEXTURE_2D);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER,draw);
        glBindFramebuffer(GL_READ_FRAMEBUFFER,read);
        glReadBuffer(readBuffer);
        glBindTexture(GL_TEXTURE_2D,texture);
        available=true;
    }
    static void bind(GLuint program,bool enabled=true) {
        glUniform1i(glGetUniformLocation(program,"uFrostEnabled"),enabled&&available);
        glUniform4f(glGetUniformLocation(program,"uBackdropViewport"),viewport[0],viewport[1],viewport[2],viewport[3]);
        glActiveTexture(GL_TEXTURE7);glBindTexture(GL_TEXTURE_2D,backdrop);
        glUniform1i(glGetUniformLocation(program,"uMenuBackdrop"),7);
        glActiveTexture(GL_TEXTURE0);
    }
    void shutdown() {
        if(backdrop)glDeleteTextures(1,&backdrop);
        if(framebuffer)glDeleteFramebuffers(1,&framebuffer);
        backdrop=framebuffer=0;available=false;
    }
};

// Legacy detailed menus use the same hit geometry for their colored interiors.
template<class VertexType,class Placement,class Entries>
std::vector<VertexType> frostedButtonFills(const Placement& placement,const Entries& entries,bool desktop) {
    std::vector<VertexType> fills;
    if(desktop)return fills;
    for(const auto& item:entries) {
        const auto center=placement.localPoint(item.worldPosition);
        const glm::vec2 r(glm::length(placement.localPoint(item.worldPosition+item.hitHalfRight)-center),
                          glm::length(placement.localPoint(item.worldPosition+item.hitHalfUp)-center));
        const auto color=glm::mix(glm::vec3(.075F),nadoc_vr::ui_style::buttonAccent(item.label),item.enabled?.045F:.02F);
        for(auto p:std::array<glm::vec2,6>{{{-r.x,-r.y},{r.x,-r.y},{r.x,r.y},{-r.x,-r.y},{r.x,r.y},{-r.x,r.y}}})
            fills.push_back({center+glm::vec3(p,0),color,1});
    }
    return fills;
}
