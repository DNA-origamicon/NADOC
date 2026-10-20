#pragma once
#include <fstream>
#include <iomanip>
#include <future>
#include <filesystem>
#include "simulation_trajectory_gallery.hpp"
#include "simulation_colour_scale.hpp"
namespace nadoc_vr {
struct SimulationRow {std::string id,label,detail;bool enabled=false,active=false;std::string kind,group;double value=0,minimum=-1e9,maximum=1e9,step=1;};
struct SimulationProgress {std::string label;float fraction=-1;bool busy=false;};
struct SimulationSnapshot {
 int version=0,ack=0;bool selected=false,hasTrajectory=false,hasScale=false;
 std::string mode,phase,message,scaleTitle;
 std::vector<SimulationRow> engines,jobs,views;
 std::vector<SimulationProgress> progress;
 simulation_study::TrajectoryState trajectory;
 simulation_study::ScaleState scale;
 float scaleMinimum=0,scaleMaximum=1;
 static SimulationSnapshot read(const std::string& path) {std::ifstream in(path);return read(in);}
 static SimulationSnapshot read(std::istream& in) {
  SimulationSnapshot s;std::string magic;int ne,nj,nv;
  if(!(in>>magic>>s.version>>s.ack>>ne>>nj>>nv>>s.selected>>std::quoted(s.mode)) || (magic!="NADOC_SIMULATIONS_2" && magic!="NADOC_SIMULATIONS_3") || s.version<1 || s.ack<0 || ne<0 || ne>10 || nj<0 || nj>10000 || nv<0 || nv>1000)throw std::runtime_error("Invalid simulation menu");
  for(auto pair:{std::pair{ne,&s.engines},std::pair{nj,&s.jobs},std::pair{nv,&s.views}})for(int i=0;i<pair.first;++i){SimulationRow r;
   if(!(in>>std::quoted(r.id)>>std::quoted(r.label)>>std::quoted(r.detail)>>r.enabled>>r.active>>std::quoted(r.kind)>>std::quoted(r.group)>>r.value>>r.minimum>>r.maximum>>r.step) || r.id.size()>100 || r.label.size()>250 || !std::isfinite(r.value)||!std::isfinite(r.minimum)||!std::isfinite(r.maximum))throw std::runtime_error("Invalid simulation control");
   pair.second->push_back(r);}
  in>>s.hasTrajectory;
  if(s.hasTrajectory){auto& t=s.trajectory;int count;
   in>>t.available>>t.first>>t.last>>t.interval>>count>>t.index>>std::quoted(s.phase)>>t.playing>>t.smooth>>t.progress>>std::quoted(s.message);
   if(magic=="NADOC_SIMULATIONS_3")in>>t.loop;
   if(t.available<0 || t.available>100000000 || t.first<1 || t.interval<1 || t.last<0 || t.last>t.available || t.index<0 || count<0 || count>100000000)throw std::runtime_error("Invalid trajectory menu");
   t.buffering=s.phase=="buffering";
   t.loadedFirst=t.first;t.loadedLast=std::max(t.first,t.last);t.loadedInterval=t.interval;t.phase=s.phase=="ready"?2:(s.phase=="loading"||s.phase=="buffering"||s.phase=="metadata")?1:0;
  }
  int n=0;if(!(in>>n)||n<0||n>16)throw std::runtime_error("Invalid progress");
  for(int i=0;i<n;++i){SimulationProgress p;in>>std::quoted(p.label)>>p.fraction>>p.busy;s.progress.push_back(p);}
  in>>s.hasScale;
  if(s.hasScale){float lo,hi;in>>std::quoted(s.scaleTitle)>>s.scaleMinimum>>s.scaleMaximum>>lo>>hi>>s.scale.palette;
   if(!std::isfinite(lo)||!std::isfinite(hi)||s.scaleMaximum<=s.scaleMinimum||s.scale.palette<0||s.scale.palette>5)throw std::runtime_error("Invalid scale");
   s.scale.low=(lo-s.scaleMinimum)/(s.scaleMaximum-s.scaleMinimum);s.scale.high=(hi-s.scaleMinimum)/(s.scaleMaximum-s.scaleMinimum);}
  if(!in)throw std::runtime_error("Incomplete simulation menu");
  return s;
 }
};
}
