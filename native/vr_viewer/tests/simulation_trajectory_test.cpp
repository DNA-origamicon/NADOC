#include "simulation_trajectory_gallery.hpp"
#include <cassert>
using namespace simulation_study;
int main(){
    // Input speed changes value gain while the cylinder retains the smallest shape.
    assert(TrajectoryRangeWheels::shape().radius==nadoc_vr::thumbwheelPreset(10,.20F).radius);
    assert(TrajectoryRangeWheels::gain(.01F,100000)==1);
    assert(TrajectoryRangeWheels::gain(.3F,100000)==10);
    assert(TrajectoryRangeWheels::gain(.8F,100000)==100);
    assert(TrajectoryRangeWheels::gain(.8F,99)==1);
    assert(TrajectoryRangeWheels::gain(.8F,999)==10);
    auto gesture=[](int available,float velocity,float hz,int field=300){
        TrajectoryState s;s.available=available;s.first=1;s.last=available;s.interval=1;
        TrajectoryRangeWheels w;w.begin(field,0);
        for(int i=1;i<=int(hz);++i)w.move(s,velocity*i/hz,1/hz);
        w.stop();return field==300?s.first:s.interval;
    };
    // One small deliberate movement is exactly one frame, independently of rate.
    for(float hz:{60.F,90.F,120.F})assert(gesture(100000,.013F,hz)==2);
    assert(gesture(100000,.24F,90)>100);
    assert(gesture(100000,.8F,90)>5000);
    assert(gesture(100000,.8F,90,302)>5000);
    TrajectoryState bounds;bounds.first=4;bounds.last=5;
    TrajectoryRangeWheels w;w.begin(300,0);w.move(bounds,.1F,.01F);assert(bounds.first==5);
    w.begin(301,0);w.move(bounds,-.1F,.01F);assert(bounds.last==5);
    w.begin(302,0);w.move(bounds,-.1F,.01F);assert(bounds.interval==1);
    w.begin(300,0);w.move(bounds,-.02F,.2F);assert(bounds.first==5); // tracking gap
    w.stop();assert(w.move(bounds,-.1F,.01F)==0); // no release momentum
    TrajectoryState t;TrajectoryGallery ui;
    for(int id:{300,301,302}){ui.action(t,id);assert(!ui.popup);}
    assert(t.count()==200 && t.phase==0);
    t.seek(.8F);t.step(50);assert(t.index==0); // No frame access before Load.
    ui.load(t);assert(t.phase==1 && ui.popup==0);
    t.seek(.8F);assert(t.index==0);
    t.update(3.F);assert(t.phase==2 && !t.playing);
    ui.edit(t,302);ui.apply(t);assert(t.phase==2); // Unchanged setup preserves prepared frames.
    t.seek(1);assert(t.index==199 && t.sourceFrame()==3981);
    t.seekSource(1001);assert(t.index==50 && t.sourceFrame()==1001);
    t.seekSource(1005);assert(t.sourceFrame()==1001);
    t.step(-10000);assert(t.index==0);t.step(10000);assert(t.index==199);
    t.playing=true;t.update(.2F);assert(!t.playing); // Stop at final loaded frame.
    ui.edit(t,302);ui.digit(0);ui.apply(t);assert(ui.popup==1 && t.phase==2);
    ui.digits="1";ui.apply(t);assert(ui.popup==0 && t.interval==1 && t.phase==0);
    t.last=499;ui.load(t);assert(t.phase==1 && ui.popup==0);
    t.invalidate();t.last=500;ui.load(t);assert(t.phase==0 && ui.popup==2);
    ui.action(t,360);assert(t.phase==0 && !ui.popup);
    t.last=100000;ui.load(t);assert(t.count()==100000 && ui.popup==2);
    ui.action(t,361);assert(t.interval==500 && t.count()==200 && t.phase==0 && !ui.popup);
    ui.load(t);t.update(3);t.seekSource(50001);assert(t.index==100 && t.sourceFrame()==50001);
    ui.edit(t,306);ui.digits="99999";assert(!ui.numberValid(t)); // Beyond last sampled frame 99501.
    ui.digits="50020";ui.apply(t);assert(t.sourceFrame()==50001 && t.phase==2);
    ui.edit(t,300);ui.digits="0";assert(!ui.numberValid(t));ui.close();
    ui.edit(t,301);ui.digits="100001";assert(!ui.numberValid(t));ui.close();
    ui.edit(t,300);ui.digits="100000";ui.apply(t);assert(t.count()==1 && t.phase==0);
    t.first=10;t.last=9;assert(!t.valid() && t.count()==0);ui.load(t);assert(t.phase==0);
    t.first=1;t.last=100000;t.interval=1;ui.load(t);ui.action(t,362);assert(t.phase==1 && !ui.popup);
    ui.action(t,304);t.update(20);assert(t.phase==0 && !t.playing);
    for(bool detailed:{false,true}){
        for(const auto& c:ui.controls(t,detailed))if(c.id==305 || c.id==311)assert(!c.enabled);
        t.start();t.update(3);for(const auto& c:ui.controls(t,detailed))if(c.id==305 || c.id==311)assert(c.enabled);
        const auto bar=ui.scrubber(detailed);
        assert(std::abs(ui.fraction(detailed,{bar.x,bar.y,0}))<1e-6F);
        assert(std::abs(ui.fraction(detailed,{bar.x+bar.z,bar.y,0})-1)<1e-6F);
        t.invalidate();
    }
}
