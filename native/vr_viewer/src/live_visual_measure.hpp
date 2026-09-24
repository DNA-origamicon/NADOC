#pragma once
#include <GL/gl.h>
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

// Measurements of final visible stencil pixels, in top-left image coordinates.
// Moments describe the complete class mask, not individual connected components.
namespace nadoc_metrics {
struct Mask {
    uint64_t n = 0;
    int x0 = 100000, y0 = 100000, x1 = -1, y1 = -1;
    double sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0;
    void add(int x, int y) {
        ++n; x0 = std::min(x0,x); y0 = std::min(y0,y);
        x1 = std::max(x1,x); y1 = std::max(y1,y);
        const double px=x+0.5, py=y+0.5;
        sx+=px; sy+=py; sxx+=px*px; syy+=py*py; sxy+=px*py;
    }
    std::string json(int id) const {
        std::ostringstream o;
        o << "{\"class_id\":" << id << ",\"pixels\":" << n;
        if (!n) return o.str()+",\"bounds\":null,\"centroid\":null,\"fill_ratio\":null,\"moment_axes\":null}";
        const double cx=sx/n, cy=sy/n, a=sxx/n-cx*cx, b=syy/n-cy*cy, c=sxy/n-cx*cy;
        const double d=std::hypot(a-b,2*c);
        o << ",\"bounds\":["<<x0<<','<<y0<<','<<x1-x0+1<<','<<y1-y0+1<<']'
          << ",\"centroid\":["<<cx<<','<<cy<<']'
          << ",\"fill_ratio\":"<<double(n)/((x1-x0+1)*(y1-y0+1))
          << ",\"moment_axes\":["<<4*std::sqrt(std::max(0.0,(a+b+d)/2))<<','
          <<4*std::sqrt(std::max(0.0,(a+b-d)/2))<<"]}";
        return o.str();
    }
};
inline std::array<Mask,8> reduce(const std::vector<uint8_t>& pixels,int x,int y,int w,int h) {
    if(w<=0 || h<=0 || pixels.size()!=size_t(w)*h) throw std::runtime_error("invalid mask dimensions");
    std::array<Mask,8> masks{};
    for(int row=0;row<h;++row) for(int col=0;col<w;++col) {
        const auto id=pixels[size_t(row)*w+col];
        if(id>0 && id<masks.size()) masks[id].add(x+col,y+h-1-row);
    }
    return masks;
}
class LiveMeasure {
    using Clock=std::chrono::steady_clock;
    bool pending_=false;
    uint64_t sequence_=0;
    std::array<double,4> roi_{0,0,1,1};
    std::array<std::string,2> eyes_{};
    Clock::time_point start_;
    std::string result_="null";
public:
    bool pending() const { return pending_; }
    const std::string& result() const { return result_; }
    void begin(uint64_t sequence, const std::array<double,4>& roi) {
        for(auto v:roi) if(!std::isfinite(v) || v<0 || v>1) throw std::runtime_error("invalid ROI");
        if(roi[2]<=0 || roi[3]<=0 || roi[0]+roi[2]>1 || roi[1]+roi[3]>1) throw std::runtime_error("invalid ROI extent");
        sequence_=sequence; roi_=roi; eyes_={}; start_=Clock::now(); pending_=true;
        result_="{\"status\":\"pending\",\"command_sequence\":"+std::to_string(sequence_)+"}";
    }
    void fail(const char* reason) {
        pending_=false;
        result_="{\"status\":\"failed\",\"command_sequence\":"+std::to_string(sequence_)+",\"error\":\""+reason+"\"}";
    }
    void expire() { if(pending_ && Clock::now()-start_>std::chrono::seconds(4)) fail("no_submitted_frame"); }
    void readEye(unsigned index,int width,int height) {
        if(!pending_ || index>=2) return;
        if(width<=0 || height<=0 || width>4096 || height>4096) { fail("invalid_dimensions"); return; }
        const int x=int(std::floor(roi_[0]*width)), y=int(std::floor(roi_[1]*height));
        const int w=std::min(width,int(std::ceil((roi_[0]+roi_[2])*width)))-x;
        const int h=std::min(height,int(std::ceil((roi_[1]+roi_[3])*height)))-y;
        std::vector<uint8_t> pixels(size_t(w)*h);
        GLint alignment; glGetIntegerv(GL_PACK_ALIGNMENT,&alignment); glPixelStorei(GL_PACK_ALIGNMENT,1);
        auto started=Clock::now();
        glReadPixels(x,height-y-h,w,h,GL_STENCIL_INDEX,GL_UNSIGNED_BYTE,pixels.data());
        glPixelStorei(GL_PACK_ALIGNMENT,alignment);
        if(glGetError()!=GL_NO_ERROR) { fail("readback_failed"); return; }
        const auto readEnd=Clock::now();
        const auto masks=reduce(pixels,x,y,w,h);
        const auto reduced=Clock::now();
        std::ostringstream o;
        o << "{\"width\":"<<width<<",\"height\":"<<height<<",\"roi\":["<<x<<','<<y<<','<<w<<','<<h<<']'
          <<",\"readback_ms\":"<<std::chrono::duration<double,std::milli>(readEnd-started).count()
          <<",\"reduce_ms\":"<<std::chrono::duration<double,std::milli>(reduced-readEnd).count()<<",\"masks\":[";
        for(int id=1;id<8;++id) { if(id>1)o<<','; o<<masks[id].json(id); }
        o<<"]}"; eyes_[index]=o.str();
    }
    void finish(bool submitted,uint64_t frame) {
        if(!pending_) return;
        if(submitted && !eyes_[0].empty() && !eyes_[1].empty()) {
            result_="{\"status\":\"complete\",\"command_sequence\":"+std::to_string(sequence_)
                +",\"frame\":"+std::to_string(frame)+",\"source\":\"application_stencil\",\"xr_end_frame_succeeded\":true,\"compositor_acknowledged\":false,\"eyes\":["+eyes_[0]+","+eyes_[1]+"]}";
            pending_=false;
        }
        eyes_={}; // Never combine eyes from different submitted frames.
    }
};
}
