#pragma once
#include <GL/gl.h>
#include <vector>
#include <sstream>
#include "spectator_mirror.hpp"
#include "scrywrite_visual.hpp"
namespace nadoc_vr {
// Read the real companion backbuffer after the submitted-eye blit, before swap.
// Deliberately excludes window decorations/desktop occlusion and compositor scanout.
struct LiveMirrorCapture {
    int width=0,height=0,eye=-1;
    SpectatorMirrorViewport viewport{};
    std::vector<uint8_t> rgb;
    void read(int w,int h,int selected,SpectatorMirrorViewport area) {
        if(w<=0||h<=0||w>4096||h>4096)return;
        width=w;height=h;eye=selected;viewport=area;
        rgb.resize(static_cast<size_t>(w)*h*3);
        GLint alignment=4,buffer=0;
        glGetIntegerv(GL_PACK_ALIGNMENT,&alignment);glGetIntegerv(GL_READ_BUFFER,&buffer);
        glPixelStorei(GL_PACK_ALIGNMENT,1);glReadBuffer(GL_BACK);
        glReadPixels(0,0,w,h,GL_RGB,GL_UNSIGNED_BYTE,rgb.data());
        glReadBuffer(buffer);glPixelStorei(GL_PACK_ALIGNMENT,alignment);
        if(glGetError()!=GL_NO_ERROR)rgb.clear();
    }
    std::string save(const std::filesystem::path& directory) const {
        if(rgb.empty())return "null";
        scrywrite::writeActorEyeCapture(directory,"mirror",rgb,width,height);
        std::ostringstream out;
        out<<"{\"source\":\"submitted_eye_blit_backbuffer\",\"eye\":\""<<(eye==0?"left":"right")
           <<"\",\"width\":"<<width<<",\"height\":"<<height<<",\"viewport_bottom_up\":["
           <<viewport.x<<','<<viewport.y<<','<<viewport.width<<','<<viewport.height<<"]}";
        return out.str();
    }
};
}
