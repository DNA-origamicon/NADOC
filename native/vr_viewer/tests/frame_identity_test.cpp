#include "frame_identity.hpp"
#include <cassert>
#include <iostream>
#include <limits>
using namespace nadoc_vr::frame_identity;
template<class F> void rejects(F fn){bool failed=false;try{fn();}catch(const std::runtime_error&){failed=true;}assert(failed);}
int main() {
    assert(!parseEnabled("off"));assert(parseEnabled("on"));rejects([]{parseEnabled("true");});
    assert(parseMode("off")==Mode::off && parseMode("on")==Mode::on && parseMode("recording")==Mode::recording);
    rejects([]{parseMode("true");});rejects([]{parseMode("auto");});
    for(bool collecting:{false,true}) {
        assert(!shouldRender(Mode::off,collecting));assert(shouldRender(Mode::on,collecting));
        assert(shouldRender(Mode::recording,collecting)==collecting);
    }
    for(const auto* bad:{"","1","0-1","1-0","-1-2","1--2","4294967296-1","1-18446744073709551616","1-2x","1-2-3","01-2","1-02"})
        rejects([&]{parseSession(bad);});
    const auto largest=parseSession("4294967295-18446744073709551615");
    assert(largest.pid==0xffffffffU && largest.startNs==std::numeric_limits<uint64_t>::max());
    const std::string known="123456789";
    assert(crc32(reinterpret_cast<const uint8_t*>(known.data()),known.size())==0xcbf43926U);
    const auto packet=encode({0x12345678U,0x0123456789abcdefULL},0xfedcba9876543210ULL,1);
    // Independently generated with Python struct.pack('>IQQ') + zlib.crc32.
    const std::string hex="4e460201123456780123456789abcdeffedcba98765432109fc2de62a55ac33c";
    constexpr char digits[]="0123456789abcdef";std::string got;
    for(auto b:packet){got+=digits[b>>4];got+=digits[b&15];}assert(got==hex);
    assert(packetCrc(packet)==0x9fc2de62U);
    for(size_t byte=0;byte<24;++byte)for(unsigned bit=0;bit<8;++bit) {
        auto broken=packet;broken[byte]^=uint8_t(1U<<bit);assert(crc32(broken.data(),24)!=packetCrc(packet));
    }
    const auto other=encode({0x12345678U,0x0123456789abcdefULL},0xfedcba9876543210ULL,0);
    assert(other[3]==0 && packetCrc(other)!=packetCrc(packet));
    const auto zero=encode(largest,0,0),full=encode(largest,std::numeric_limits<uint64_t>::max(),1);
    for(size_t i=16;i<24;++i){assert(zero[i]==0);assert(full[i]==255);}
    rejects([]{encode({},1,0);});rejects([&]{encode(largest,1,2);});
    assert((cell(packet,0,0)==Color{255,255,255}));assert((cell(packet,23,0)==Color{255,255,255}));
    assert((cell(packet,0,23)==Color{255,255,255}));assert((cell(packet,23,23)==Color{255,255,255}));
    for(unsigned y=0;y<16;++y)for(unsigned x=0;x<16;++x) {
        const auto rgb=cell(packet,x+4,y+4);const auto bit=y*16+x;
        assert(rgb[0]==rgb[1] && rgb[1]==rgb[2]);assert((rgb[0]==255)==bool((packet[bit/8]>>(7-bit%8))&1U));
    }
    assert((cell(packet,10,0)==Color{0,0,0}));rejects([&]{cell(packet,24,0);});
    const auto rect=rectangle(1852,2056);assert(rect.x==830 && rect.y==726 && rect.width==192 && rect.height==192);
    rejects([]{rectangle(191,2056);});rejects([]{rectangle(1852,100);});rejects([]{rectangle(0xffffffffU,2056);});
    assert(configJson(false)=="{\"enabled\":false}");
    assert(configJson(true,largest).find("\"protocol\":\"nadoc-frame-v2\"")!=std::string::npos);
    assert(configJson(true,largest).find("18446744073709551615")!=std::string::npos);
    const auto recording=configJson(Mode::recording,largest);
    assert(recording.find("\"enabled\":true")!=std::string::npos);
    assert(recording.find("\"activation_mode\":\"recording\"")!=std::string::npos);
    assert(recording.find("\"recording_only\":true")!=std::string::npos);
    std::cout<<"Frame identity protocol, bounds, checksums and layout passed\n";
}
