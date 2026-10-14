#pragma once
// Submitted-eye identity protocol. No GL, clocks, files, or decoding guesses here.
#include <array>
#include <charconv>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>

namespace nadoc_vr::frame_identity {
inline constexpr unsigned version=2, gridCells=24, payloadCells=16, cellPixels=8;
using Packet=std::array<uint8_t,32>;
using Color=std::array<uint8_t,3>;
struct Session {uint32_t pid=0;uint64_t startNs=0;};
struct Rect {int x=0,y=0,width=0,height=0;};
struct Receipt {
    bool rendered=false;
    uint64_t frame=0;
    uint32_t packetCrc32=0;
    Rect rect;
    int64_t hostStartNs=0,hostEndNs=0;
};
enum class Mode { off, on, recording };
inline Mode parseMode(std::string_view text) {
    if(text=="on")return Mode::on;
    if(text=="off")return Mode::off;
    if(text=="recording")return Mode::recording;
    throw std::runtime_error("submitted-frame-marker requires on, off or recording");
}
inline const char* modeName(Mode mode) {
    return mode==Mode::recording?"recording":mode==Mode::on?"on":"off";
}
inline bool shouldRender(Mode mode,bool journalCollecting) {
    return mode==Mode::on || (mode==Mode::recording && journalCollecting);
}
inline uint32_t crc32(const uint8_t* data,size_t bytes) {
    uint32_t crc=0xffffffffU;
    for(size_t i=0;i<bytes;++i) {
        crc^=data[i];
        for(unsigned j=0;j<8;++j)crc=(crc>>1)^((0U-(crc&1U))&0xedb88320U);
    }
    return crc^0xffffffffU;
}
inline uint64_t decimal(std::string_view text) {
    uint64_t value=0;
    if(text.empty() || (text.size()>1 && text.front()=='0') || text.find_first_not_of("0123456789")!=std::string_view::npos)
        throw std::runtime_error("Frame marker session requires decimal PID-start_ns");
    const auto parsed=std::from_chars(text.data(),text.data()+text.size(),value);
    if(parsed.ec!=std::errc{} || parsed.ptr!=text.data()+text.size() || !value)
        throw std::runtime_error("Frame marker session identity is zero or out of range");
    return value;
}
inline Session parseSession(std::string_view text) {
    const auto split=text.find('-');
    if(split==std::string_view::npos)throw std::runtime_error("Frame marker requires a live session");
    const auto pid=decimal(text.substr(0,split)),start=decimal(text.substr(split+1));
    if(pid>std::numeric_limits<uint32_t>::max())throw std::runtime_error("Frame marker PID exceeds uint32");
    return {static_cast<uint32_t>(pid),start};
}
inline bool parseEnabled(std::string_view text) {
    if(text=="on")return true;
    if(text=="off")return false;
    throw std::runtime_error("submitted-frame-marker requires on or off");
}
inline void put(Packet& packet,size_t offset,uint64_t value,unsigned bytes) {
    for(unsigned i=0;i<bytes;++i)packet[offset+i]=uint8_t(value>>(8*(bytes-1-i)));
}
inline uint32_t packetCrc(const Packet& packet) {
    return (uint32_t(packet[24])<<24)|(uint32_t(packet[25])<<16)|(uint32_t(packet[26])<<8)|packet[27];
}
inline Packet encode(Session session,uint64_t frame,unsigned eye) {
    if(!session.pid || !session.startNs || eye>1)throw std::runtime_error("Invalid frame marker identity");
    Packet packet{};packet[0]='N';packet[1]='F';packet[2]=version;packet[3]=uint8_t(eye);
    put(packet,4,session.pid,4);put(packet,8,session.startNs,8);put(packet,16,frame,8);
    put(packet,24,crc32(packet.data(),24),4);
    packet[28]=0xa5;packet[29]=0x5a;packet[30]=0xc3;packet[31]=0x3c;
    return packet;
}
inline Color cell(const Packet& packet,unsigned x,unsigned y) {
    if(x>=gridCells || y>=gridCells)throw std::runtime_error("Frame marker cell out of bounds");
    if((x<3 || x>=21) && (y<3 || y>=21))return {255,255,255};
    if(x>=4 && x<20 && y>=4 && y<20) {
        const unsigned bit=(y-4)*16+x-4;
        const uint8_t value=(packet[bit/8]>>(7-bit%8)&1U)?255:0;
        return {value,value,value};
    }
    return {0,0,0};
}
inline Rect rectangle(uint32_t width,uint32_t height) {
    constexpr int side=gridCells*cellPixels;
    if(width>uint32_t(std::numeric_limits<int>::max()) || height>uint32_t(std::numeric_limits<int>::max()))
        throw std::runtime_error("Frame marker image exceeds integer coordinates");
    const int x=int(width)/2-side/2,y=int((uint64_t(height)*40+50)/100)-side/2;
    if(x<0 || y<0 || uint64_t(x+side)>width || uint64_t(y+side)>height)
        throw std::runtime_error("Frame marker does not fit the submitted eye");
    return {x,y,side,side};
}
inline std::string receiptJson(const Receipt& value) {
    return "{\"rendered\":"+std::string(value.rendered?"true":"false")+",\"frame\":"+std::to_string(value.frame)+
        ",\"packet_crc32\":"+std::to_string(value.packetCrc32)+",\"rectangle_xywh\":["+
        std::to_string(value.rect.x)+","+std::to_string(value.rect.y)+","+std::to_string(value.rect.width)+","+
        std::to_string(value.rect.height)+"],\"host_draw_start_ns\":"+std::to_string(value.hostStartNs)+
        ",\"host_draw_end_ns\":"+std::to_string(value.hostEndNs)+"}";
}
inline std::string configJson(Mode mode,Session session={}) {
    if(mode==Mode::off)return "{\"enabled\":false}";
    return "{\"enabled\":true,\"activation_mode\":\""+std::string(modeName(mode))+"\",\"recording_only\":"+
        (mode==Mode::recording?"true":"false")+",\"protocol\":\"nadoc-frame-v2\",\"version\":2,\"session_pid\":"+std::to_string(session.pid)+
        ",\"session_start_ns\":"+std::to_string(session.startNs)+
        ",\"coordinate_space\":\"application_eye_undistorted\",\"coordinate_convention\":\"top-left pixel centers at integer indices; rectangle_xywh uses half-open pixel boundaries\""
        ",\"grid_cells\":24,\"cell_pixels\":8,\"payload_rect_cells\":[4,4,16,16],\"center_fraction_xy\":[0.5,0.40]"
        ",\"packet_bytes\":32,\"byte_order\":\"big-endian\",\"bit_order\":\"row-major MSB-first\",\"magic_hex\":\"4e46\",\"pad_hex\":\"a55ac33c\""
        ",\"fields\":[\"magic:2\",\"version:1\",\"eye:1\",\"pid:4\",\"session_start_ns:8\",\"app_frame:8\",\"crc32:4\",\"pad:4\"]"
        ",\"crc\":\"CRC-32/ISO-HDLC IEEE over first24bytes (zlib.crc32)\",\"eye_values\":{\"left\":0,\"right\":1}"
        ",\"fiducials\":[{\"corner\":\"TL\",\"rect_cells\":[0,0,3,3],\"rgb\":[255,255,255]},{\"corner\":\"TR\",\"rect_cells\":[21,0,3,3],\"rgb\":[255,255,255]},{\"corner\":\"BL\",\"rect_cells\":[0,21,3,3],\"rgb\":[255,255,255]},{\"corner\":\"BR\",\"rect_cells\":[21,21,3,3],\"rgb\":[255,255,255]}]"
        ",\"localization_channel\":\"green\",\"corner_order\":\"top-left image coordinates; strict packet and CRC check\",\"draw_stage\":\"after scene/UI; before application-eye capture and xrReleaseSwapchainImage\",\"draw_calls_per_eye\":1,\"pixel_readback\":false"
        ",\"identity_limit\":\"identifies submitted image pixels after successful decode; does not establish photon timing or separate scene GPU coherence\"}";
}
inline std::string configJson(bool enabled,Session session={}) {
    return configJson(enabled?Mode::on:Mode::off,session);
}
} // namespace nadoc_vr::frame_identity
