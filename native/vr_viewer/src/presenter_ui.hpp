#pragma once
#include <future>
// Guest presence uses the same tracking-space vertices and panel pixels as XR.
// Texture readback/PNG work happens only when a visible panel changes.
namespace nadoc_vr {
inline std::string presenterBase64(const std::vector<uint8_t>& bytes) {
    constexpr char alphabet[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;out.reserve((bytes.size()+2)/3*4);
    for(size_t i=0;i<bytes.size();i+=3){const unsigned v=(unsigned(bytes[i])<<16)|(i+1<bytes.size()?unsigned(bytes[i+1])<<8:0)|(i+2<bytes.size()?bytes[i+2]:0);
        out+=alphabet[(v>>18)&63];out+=alphabet[(v>>12)&63];out+=i+1<bytes.size()?alphabet[(v>>6)&63]:'=';out+=i+2<bytes.size()?alphabet[v&63]:'=';}
    return out;
}
class PresenterTexture {
    struct Image {uint64_t version;GLuint texture;std::string png;};
    uint64_t version_=~uint64_t(0),pendingVersion_=0;
    GLuint texture_=0,pendingTexture_=0,pbo_=0;
    GLsync fence_=nullptr;
    int width_=0,height_=0,crop_=0;
    bool topDown_=false;
    std::string png_;
    std::future<Image> encoding_;
    static std::string encode(std::vector<uint8_t> rgba,int width,int height,int crop,bool topDown) {
        // X11 desktop capture is RGB; its unused fourth byte is not opacity.
        if(topDown && !crop)for(size_t i=3;i<rgba.size();i+=4)rgba[i]=255;
        const int w=crop?std::min(crop,width):width,h=crop?std::min(crop,height):height;
        std::vector<uint8_t> scan(size_t(w*4+1)*h);
        for(int y=0;y<h;++y){auto* dst=scan.data()+size_t(y)*(w*4+1);*dst++=1;
            const auto* src=rgba.data()+size_t(topDown?y:h-1-y)*width*4;
            for(int x=0;x<w*4;++x)dst[x]=uint8_t(src[x]-(x>=4?src[x-4]:0));}
        uLongf length=compressBound(scan.size());std::vector<uint8_t> compressed(length);
        if(compress2(compressed.data(),&length,scan.data(),scan.size(),Z_BEST_SPEED)!=Z_OK)return {};
        compressed.resize(length);std::vector<uint8_t> png{137,80,78,71,13,10,26,10},header;
        scrywrite::appendPngUint32(header,w);scrywrite::appendPngUint32(header,h);header.insert(header.end(),{8,6,0,0,0});
        scrywrite::appendPngChunk(png,"IHDR",header);scrywrite::appendPngChunk(png,"IDAT",compressed);scrywrite::appendPngChunk(png,"IEND",{});
        return presenterBase64(png);
    }
 public:
    void shutdown() {
        if(encoding_.valid())encoding_.wait();
        if(fence_)glDeleteSync(fence_);
        if(pbo_)glDeleteBuffers(1,&pbo_);
        fence_=nullptr;pbo_=0;
    }
    const std::string& read(GLuint texture,uint64_t version,int crop=0,bool topDown=false) {
        // One capture/encode in flight per panel. Poll without waiting; changing
        // menus coalesce to their newest version after the current job completes.
        if(encoding_.valid()) {
            if(encoding_.wait_for(std::chrono::seconds(0))!=std::future_status::ready)return png_;
            auto image=encoding_.get();
            if(!image.png.empty()){png_=std::move(image.png);version_=image.version;texture_=image.texture;}
        }
        if(fence_) {
            const auto status=glClientWaitSync(fence_,0,0);
            if(status!=GL_ALREADY_SIGNALED && status!=GL_CONDITION_SATISFIED)return png_;
            GLint previous=0;glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING,&previous);
            glBindBuffer(GL_PIXEL_PACK_BUFFER,pbo_);
            const size_t size=size_t(width_)*height_*4;
            const auto* source=static_cast<const uint8_t*>(glMapBufferRange(GL_PIXEL_PACK_BUFFER,0,size,GL_MAP_READ_BIT));
            std::vector<uint8_t> rgba;
            if(source){rgba.assign(source,source+size);glUnmapBuffer(GL_PIXEL_PACK_BUFFER);}
            glBindBuffer(GL_PIXEL_PACK_BUFFER,previous);glDeleteSync(fence_);fence_=nullptr;
            if(!rgba.empty())encoding_=std::async(std::launch::async,[pixels=std::move(rgba),w=width_,h=height_,c=crop_,top=topDown_,v=pendingVersion_,t=pendingTexture_]() mutable {
                return Image{v,t,encode(std::move(pixels),w,h,c,top)};
            });
            return png_;
        }
        if(texture==texture_ && version==version_)return png_;
        GLint previousTexture=0,previousBuffer=0,pack=4,row=0,width=0,height=0;
        glGetIntegerv(GL_TEXTURE_BINDING_2D,&previousTexture);glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING,&previousBuffer);
        glGetIntegerv(GL_PACK_ALIGNMENT,&pack);glGetIntegerv(GL_PACK_ROW_LENGTH,&row);
        glBindTexture(GL_TEXTURE_2D,texture);glGetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_WIDTH,&width);glGetTexLevelParameteriv(GL_TEXTURE_2D,0,GL_TEXTURE_HEIGHT,&height);
        if(width<=0||height<=0||width>8192||height>8192){glBindTexture(GL_TEXTURE_2D,previousTexture);return png_;}
        if(!pbo_)glGenBuffers(1,&pbo_);
        glBindBuffer(GL_PIXEL_PACK_BUFFER,pbo_);glBufferData(GL_PIXEL_PACK_BUFFER,size_t(width)*height*4,nullptr,GL_STREAM_READ);
        glPixelStorei(GL_PACK_ALIGNMENT,1);glPixelStorei(GL_PACK_ROW_LENGTH,0);
        glGetTexImage(GL_TEXTURE_2D,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
        fence_=glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);glFlush();
        glPixelStorei(GL_PACK_ALIGNMENT,pack);glPixelStorei(GL_PACK_ROW_LENGTH,row);
        glBindBuffer(GL_PIXEL_PACK_BUFFER,previousBuffer);glBindTexture(GL_TEXTURE_2D,previousTexture);
        width_=width;height_=height;crop_=crop;topDown_=topDown;pendingVersion_=version;pendingTexture_=texture;
        return png_;
    }
};
class PresenterUI {
    std::array<PresenterTexture,5> textures_;
 public:
    void shutdown(){for(auto& texture:textures_)texture.shutdown();}
    template<class Vertex,class Sidebars,class Views,class Surface,class Desktop>
    void write(std::ostream& out,const std::vector<Vertex>& guides,size_t count,Sidebars& sidebars,Views& views,
        Desktop& screen,const DesktopPanel& detached,Surface& desktopFrame) {
        out<<",\"ui\":{\"lines\":[";bool comma=false;
        auto vertex=[&](glm::vec3 p,glm::vec3 c){if(comma)out<<',';comma=true;out<<p.x<<','<<p.y<<','<<p.z<<','<<c.r<<','<<c.g<<','<<c.b;};
        for(size_t i=0;i<std::min(count,guides.size());++i)vertex(guides[i].position,guides[i].color);
        if(views.open)for(int i:views.hover)if(i>=0){const auto c=views.cell(i);const glm::vec2 d{180.F/768,50.F/768};
            const std::array<glm::vec2,4> corners{{c-d,c+glm::vec2(d.x,-d.y),c+d,c+glm::vec2(-d.x,d.y)}};
            for(int j=0;j<4;++j)for(int k:{j,(j+1)%4})vertex(views.world(corners[k])+views.orientation*glm::vec3(0,0,.001F),{1,.7F,.1F});}
        out<<"],\"panels\":[";comma=false;
        auto panel=[&](const char* id,size_t slot,GLuint texture,uint64_t version,std::array<glm::vec3,4> corners,int crop=0,bool topDown=false){
            if(!texture)return;
            const auto& png=textures_[slot].read(texture,version,crop,topDown);if(png.empty())return;
            if(comma)out<<',';
            comma=true;out<<"{\"id\":\""<<id<<"\",\"png\":\""<<png<<"\",\"corners\":[";
            for(size_t i=0;i<4;++i){if(i)out<<',';out<<corners[i].x<<','<<corners[i].y<<','<<corners[i].z;}out<<"]}";
        };
        auto corners=[](const MenuPlacement& p,const MenuPanelBounds& b,float z){return std::array<glm::vec3,4>{{p.worldPoint({b.minimum.x,b.maximum.y,z}),p.worldPoint({b.minimum.x,b.minimum.y,z}),p.worldPoint({b.maximum.x,b.maximum.y,z}),p.worldPoint({b.maximum.x,b.minimum.y,z})}};};
        for(size_t i=0;i<2;++i)if(sidebars.menus[i].open)panel(i?"right-menu":"left-menu",i,sidebars.surfaces[i].presenterTexture(),sidebars.surfaces[i].stats().updates,corners(sidebars.menus[i].placement,sidebars.menus[i].bounds(),.002F));
        if(views.open&&views.version)panel("view-tools",2,views.texture,views.version,{{views.world({0,0}),views.world({0,1}),views.world({1,0}),views.world({1,1})}},768,true);
        if(detached.open) {
            panel("desktop",3,screen.presenterTexture(),screen.presenterVersion(),corners(detached.placement,detached.content(),.004F),0,true);
            panel("desktop-frame",4,desktopFrame.presenterTexture(),desktopFrame.stats().updates,corners(detached.placement,detached.chromeBounds(),.008F));
        }
        out<<"]}";
    }
};
}
