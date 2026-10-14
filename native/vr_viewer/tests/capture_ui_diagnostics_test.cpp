#include "capture_ui_diagnostics.hpp"
#include <cassert>
#include <iostream>

using nadoc_vr::CaptureUiDiagnostics;
using nadoc_vr::CaptureUiFrame;
namespace { uint64_t ticks=100,calls=0;uint64_t clockSpy(){++calls;return ticks+=10;} }
int main() {
    CaptureUiDiagnostics diag(clockSpy);
    diag.begin(nullptr);assert(diag.stamp()==0);
    diag.request(0,.2F,12);diag.dispatched(-1,0,0,-1);diag.sidebar(0,true,"idle");diag.texture(0,true,0);
    {CaptureUiDiagnostics::Scope scope(&diag,CaptureUiDiagnostics::Kind::menuDraw,0);}
    assert(calls==0);
    CaptureUiFrame frame;diag.begin(&frame);
    diag.sidebar(0,true,"first");assert(!frame.sidebars[0].changeValid);
    const auto token=diag.request(1,.4F,123);const auto start=diag.stamp();diag.dispatched(token,1,start,-5);
    assert(frame.requested[1]==1 && frame.dispatched[1]==1 && frame.failed[1]==1);
    assert(frame.totalNs[1]==10 && frame.maxNs[1]==10 && frame.events[0].result==-5);
    diag.request(0,.3F,124);assert(!frame.events[1].dispatched);
    for(unsigned i=0;i<20;++i){const auto t=diag.request(0,.3F,125);const auto s=diag.stamp();diag.dispatched(t,0,s,0);}
    assert(frame.requested[0]==21 && frame.dispatched[0]==20);
    assert(frame.eventCount==16 && frame.eventOverflow==6 && frame.totalNs[0]==200);
    diag.texture(0,true,diag.stamp());diag.texture(0,false,diag.stamp());
    {CaptureUiDiagnostics::Scope scope(&diag,CaptureUiDiagnostics::Kind::sidebarDraw,0);}
    {CaptureUiDiagnostics::Scope scope(&diag,CaptureUiDiagnostics::Kind::menuDraw,1);}
    {CaptureUiDiagnostics::Scope scope(&diag,CaptureUiDiagnostics::Kind::backdropCopy,1);}
    assert(frame.sidebars[0].updates==1 && frame.sidebars[0].hits==1 && frame.sidebars[0].drawCalls==1);
    assert(frame.eyes[1].menuCalls==1 && frame.eyes[1].copyCalls==1 && !frame.eyes[0].menuCalls);
    assert(frame.clockQueries==calls && frame.clockErrors==0);
    const auto json=CaptureUiDiagnostics::json(frame);
    assert(json.find("\"xr_result\":-5")!=std::string::npos && json.find("\"xr_result\":null")!=std::string::npos);
    assert(json.find("\"events_overflow\":6")!=std::string::npos);
    diag.end();const auto before=calls;assert(diag.stamp()==0 && calls==before);
    diag.begin(&frame);diag.sidebar(0,true,"second");assert(frame.sidebars[0].changed && frame.sidebars[0].changeValid);
    assert(frame.eventCount==0 && frame.sidebars[0].updates==0);
    diag.end();diag.begin(&frame);diag.sidebar(0,true,std::string(200,'x'));
    assert(frame.sidebars[0].truncated && !frame.sidebars[0].changeValid);
    diag.end();diag.begin(nullptr);diag.begin(&frame);diag.sidebar(0,true,"new capture");
    assert(!frame.sidebars[0].previousKnown);
    std::cout<<"Capture-only clock gating, bounded haptic failure/overflow accounting, hover validity and independent timing counters passed; bytes/frame="<<sizeof(CaptureUiFrame)<<'\n';
}
