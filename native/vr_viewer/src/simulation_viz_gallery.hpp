#pragma once
#include <algorithm>
#include <array>
#include "simulation_colour_scale.hpp"
#include "simulation_trajectory_gallery.hpp"
#include <string>
#include <vector>

// Review-only inventory translated from frontend/index.html simulation display
// cards and ui/flex_scale.js. No engine calls or molecular state are connected.
namespace simulation_study {
struct Mode {int id;const char* label;const char* description;};
inline std::vector<Mode> modes(int engine) {
    const Mode off{0,"NATIVE MODEL","Original design positions"},shape{1,"LATEST SHAPE","Latest available coordinates"},
        flex{2,"FLEXIBILITY / RMSF","Colour by positional fluctuations"},dev{3,"DEVIATION","Displacement from the design"},
        cando{4,"CANDO OUTPUT","Cylinder output at 298 K"},beads{5,"CG BEADS","Coarse grained / 5 BP per bead"},
        strain{6,"STRAIN MAP","Local backbone or pairing strain"},occ{7,"OCCUPANCY CLOUDS","Likely configurations and populations"},
        traj{8,"TRAJECTORY","Play and inspect sampled frames"},full{9,"FULL TRAJECTORY","Every frame of this job"},
        photo{10,"T-T PROPENSITY","Geometric score / not probability"},paths{11,"ION PATHS","Ion motion around the current frame"},
        vectors{12,"ION VECTOR FIELD","Binned displacement and magnitude"};
    if(engine==0)return {off,{1,"PREDICTED SHAPE","Thermal shape at 298 K"},flex,dev,cando};
    if(engine==1)return {off,{1,"PREDICTED SHAPE","Thermal shape at 298 K"},flex,dev,cando,traj};
    if(engine==2)return {off,{1,"RELAXED SHAPE","Latest relaxed coordinates"},beads,flex,dev,strain};
    if(engine==3)return {off,shape,flex,dev,strain,occ,{8,"CHAIN TRAJECTORY","About 200 strided frames"},full};
    if(engine==4)return {off,shape,flex,photo,occ,traj,paths,vectors};
    return {off,{13,"DISPLAY PREDICTION","Session result / Full representation"}};
}
struct State {
    int mode=0,group=0,optionPage=0,load=0,frame=0;bool inspecting=false,playing=false;float elapsed=0;
    std::array<int,64> values{};
    std::array<ScaleState,14> scales{};
    std::array<TrajectoryState,2> trajectories{};
    State(){trajectories[1].interval=1;trajectories[1].last=100000;values[9]=1;values[17]=1;values[37]=1;values[49]=1;scales[3].palette=4;scales[4].palette=3;scales[6].palette=5;scales[10].palette=1;}
};
struct Field {int id;std::string label;std::vector<std::string> choices;int group=0;};
inline std::vector<Field> fields(int engine,const State& s) {
    std::vector<Field> f;
    const auto add=[&](int id,std::string label,std::vector<std::string> values,int group=0){f.push_back({id,label,values,group});};
    const auto toggle=[&](int id,std::string label,int group=0){add(id,label,{"OFF","ON"},group);};
    const int m=s.mode;
    if(m==0)add(0,"POSITIONS",{"NATIVE DESIGN"});
    if(m==1 && engine==4)add(1,"REMOTE FRAME",{"REFRESH"});
    if(m==1 && engine<2)add(2,"TEMPERATURE",{"298 K"});
    if(m==5)add(3,"RESOLUTION",{"5 BP / BEAD"});
    if(m==6 && engine==3){add(4,"METRIC",{"BACKBONE FENE","BASE PAIRING"});toggle(5,"DSDNA ONLY");}
    if(m==6 && engine==2)add(4,"METRIC",{"BACKBONE STRAIN"});
    if(m==7){
        add(6,"STATES",{"AUTO","2","3","4","5","6"});
        if(engine==3)add(7,"COORDINATES",{"ALL NUCLEOTIDES","PAIR MIDPOINTS"});
        if(engine==4){add(8,"SAMPLING",{"FAST / 200","FULL / ALL"});toggle(10,"BASE DENSITY");}
        add(11,"ANALYSE",{"WHOLE STRUCTURE","SPECIFIC ELEMENTS"});
        add(12,"RECOMPUTE",{"LOAD SAMPLE"});
        if(s.values[11]){
            add(13,"FIT FRAME",{"SELECTION","EACH JUNCTION","WHOLE STRUCTURE"},1);
            add(14,"SCOPE",{"ADD SELECTION"},1);add(15,"SCOPE",{"CLEAR"},1);toggle(9,"HIGHLIGHT SCOPE",1);
            add(16,"ELEMENTS",{s.values[16]?"2 SAMPLE ELEMENTS":"NONE SELECTED"},1);
        }
    }
    if(m==8 || m==9){
        if(engine==4)add(18,"FRAME INTERVAL",{"20","1","5","50","100","1000"});
        if(engine>=3)toggle(17,"SMOOTH PLAYBACK");
        add(19,"PLAYBACK",{s.playing?"PAUSE":"PLAY"});
        add(20,"FRAME",{"PREVIOUS"});add(21,"FRAME",{"NEXT"});add(22,"SEEK",{"+ 20 FRAMES"});
    }
    if(m==10)add(23,"SCORE",{"RELATIVE GEOMETRY"});
    if(m==11){
        add(24,"FRAMES BEFORE",{"10","20","50","5"});add(25,"FRAMES AFTER",{"10","20","50","5"});
        add(26,"LINE WIDTH",{"2 PX","3 PX","5 PX","1 PX"});add(27,"COLOUR",{"ION SPECIES","EARLY TO LATE"});
        add(28,"PATHS SHOWN",{"100%","75%","50%","25%"});add(29,"ION DATA",{"RELOAD"});
    }
    if(m==12){
        add(30,"SPECIES",{"NA+","CL-","MG2+","K+","CA2+"});add(31,"DENSITY BINS",{"14","7","21","28"});
        add(32,"ARROW SCALE",{"1.0","0.5","2.0","4.0"});add(33,"MAGNITUDE",{"ARROW SIZE","COLOUR CODED"});
        add(29,"ION DATA",{"RELOAD"});
    }
    if(m==2 || m==3 || m==4 || m==6 || m==10){
        add(34,"COLOUR MAP",{"VIRIDIS","TURBO","JET","PLASMA"});
        add(35,"LOWER BOUND",{"DATA MIN","10% OF RANGE","25% OF RANGE"});
        add(36,"UPPER BOUND",{"DATA MAX","90% OF RANGE","75% OF RANGE"});add(38,"COLOUR RANGE",{"RESET"});
    }
    if(engine==3){toggle(37,"ALIGN TO DESIGN",2);add(39,"SURFACE DETAIL",{"COARSE / FAST","FINE / REBUILD"},2);}
    if(engine==4){
        toggle(40,"WATER",2);if(s.values[40])add(41,"WATER SCOPE",{"HYDRATION / 5 A","WHOLE BOX"},2);
        toggle(42,"IONS",2);toggle(43,"PERIODIC BOX",2);toggle(44,"WELD PAIR / CPD",2);
        if(s.values[44]){toggle(45,"TRACE OVER RUN",2);add(46,"TRACE METRIC",{"DISTANCE","TWIST ETA","PROPENSITY K"},2);toggle(48,"UMBRELLA PREVIEW",2);}
    }
    if(m==13){toggle(49,"SHOW PREDICTION");add(50,"REPRESENTATION",{"FULL REQUIRED"});}
    return f;
}
inline void edit(State& s,const Field& f) {
    if(f.id==1 || f.id==12 || f.id==29){s.load=1;s.playing=false;}
    else if(f.id==14)s.values[16]=1;
    else if(f.id==15)s.values[16]=0;
    else if(f.id==19)s.playing=!s.playing;
    else if(f.id==20)s.frame=std::max(0,s.frame-1);
    else if(f.id==21)s.frame=std::min(199,s.frame+1);
    else if(f.id==22)s.frame=(s.frame+20)%200;
    else if(f.id==38)s.values[35]=s.values[36]=0;
    else if(f.choices.size()>1)s.values[f.id]=(s.values[f.id]+1)%int(f.choices.size());
}
}
