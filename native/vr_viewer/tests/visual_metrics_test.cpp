#include "../src/live_visual_measure.hpp"
#include <cassert>
int main() {
    // Bottom-up GL buffer: asymmetric mask catches vertical inversion and ROI offsets.
    const std::vector<uint8_t> pixels={0,3,3,0, 0,3,3,0, 0,0,0,0};
    const auto masks=nadoc_metrics::reduce(pixels,10,20,4,3);
    const auto& m=masks[3];
    assert(m.n==4 && m.x0==11 && m.y0==21 && m.x1==12 && m.y1==22);
    assert(m.sx/m.n==12 && m.sy/m.n==22);
    assert(m.json(3).find("\"fill_ratio\":1")!=std::string::npos);
    assert(masks[1].json(1).find("\"centroid\":null")!=std::string::npos);
    std::vector<uint8_t> circle(41*41,0);
    for(int y=0;y<41;++y) for(int x=0;x<41;++x)
        if((x-20)*(x-20)+(y-20)*(y-20)<=100) circle[y*41+x]=5;
    const auto disk=nadoc_metrics::reduce(circle,0,0,41,41)[5];
    assert(disk.n==317 && disk.x1-disk.x0+1==21 && disk.y1-disk.y0+1==21);
    assert(disk.sx/disk.n==20.5 && disk.sy/disk.n==20.5);
    bool rejected=false;
    try { nadoc_metrics::reduce(pixels,0,0,2,2); } catch(const std::runtime_error&) { rejected=true; }
    assert(rejected);
    nadoc_metrics::LiveMeasure live;
    rejected=false;
    try { live.begin(1,{0.9,0,0.2,1}); } catch(const std::runtime_error&) { rejected=true; }
    assert(rejected && !live.pending());
    live.begin(2,{0,0,1,1});
    live.finish(true,7); // A submitted frame without eye pixels cannot complete.
    assert(live.pending());
    live.fail("test");
    assert(!live.pending() && live.result().find("failed")!=std::string::npos);
}
