#pragma once
// Optional startup-only route evidence. Never identifies a DRM lease from a
// pathname alone, enumerates arbitrary file contents, or performs driver ioctls.
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <climits>
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <fcntl.h>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#include <vector>

namespace nadoc_capture {
inline bool numericSuffix(const std::string& value,const std::string& prefix) {
  return value.size()>prefix.size() && value.compare(0,prefix.size(),prefix)==0 &&
    std::all_of(value.begin()+prefix.size(),value.end(),[](char c){return c>='0' && c<='9';});
}
inline bool allowedFdTarget(const std::string& target) {
  return numericSuffix(target,"/dev/nvidia") || numericSuffix(target,"/dev/nvidia-caps/nvidia-cap") ||
    numericSuffix(target,"/dev/dri/card") || numericSuffix(target,"/dev/dri/renderD") ||
    target=="/dev/nvidiactl" || target=="/dev/nvidia-modeset" || target=="/dev/nvidia-uvm" || target=="/dev/nvidia-uvm-tools" ||
    target=="anon_inode:sync_file" || target=="anon_inode:[sync_file]" ||
    target=="anon_inode:dmabuf" || target=="anon_inode:[dmabuf]" ||
    target=="anon_inode:drm_syncobj" || target=="anon_inode:[drm_syncobj]";
}
inline std::string quoted(const std::string& value) {
  std::ostringstream out; out<<'"';
  constexpr char hex[]="0123456789abcdef";
  for(unsigned char c:value) {
    if(c=='"' || c=='\\') out<<'\\'<<c;
    else if(c<32) out<<"\\u00"<<hex[c>>4]<<hex[c&15];
    else out<<c;
  }
  out<<'"'; return out.str();
}
inline bool allowedFdInfoKey(const std::string& key) {
  return key=="drm-driver" || key=="drm-client-id" || key=="drm-pdev" || key=="drm-lease-id" || key=="lease-id";
}
inline std::string selectedFdInfo(const std::string& text) {
  std::istringstream lines(text); std::string line; std::ostringstream out; bool first=true;
  out<<'{';
  while(std::getline(lines,line)) {
    const auto colon=line.find(':'); if(colon==std::string::npos) continue;
    const auto key=line.substr(0,colon); if(!allowedFdInfoKey(key)) continue;
    auto value=line.substr(colon+1,256); auto begin=value.find_first_not_of(" \t\r");
    value=begin==std::string::npos?"":value.substr(begin); auto end=value.find_last_not_of(" \t\r"); if(end!=std::string::npos) value.resize(end+1);
    if(!first) out<<',';
    first=false; out<<quoted(key)<<':'<<quoted(value);
  }
  out<<'}'; return out.str();
}
inline std::string fdRouteSnapshot() {
  const auto start=std::chrono::steady_clock::now();
  constexpr size_t maxScanned=4096,maxMatched=128,linkCapacity=512,infoCapacity=4096;
  DIR* directory=opendir("/proc/self/fd");
  if(!directory) return ",\"snapshot_error_errno\":"+std::to_string(errno);
  struct CloseDirectory { DIR* value; ~CloseDirectory(){closedir(value);} } close{directory};
  std::vector<std::string> matches; size_t scanned=0,races=0; bool truncated=false;
  while(auto* entry=readdir(directory)) {
    const std::string number=entry->d_name;
    if(number.empty() || !std::all_of(number.begin(),number.end(),[](char c){return c>='0' && c<='9';})) continue;
    if(scanned>=maxScanned || matches.size()>=maxMatched) { truncated=true; break; }
    scanned++; const unsigned long numeric=std::strtoul(number.c_str(),nullptr,10); if(numeric>INT_MAX) continue;
    const std::string path="/proc/self/fd/"+number; char link[linkCapacity];
    const ssize_t n=readlink(path.c_str(),link,sizeof(link)); if(n<=0 || size_t(n)==sizeof(link)) continue;
    const std::string target(link,n); if(!allowedFdTarget(target)) continue;
    struct stat st{}; const bool statValid=fstat(int(numeric),&st)==0;
    char info[infoCapacity]; ssize_t length=-1;
    const int descriptor=open(("/proc/self/fdinfo/"+number).c_str(),O_RDONLY|O_CLOEXEC);
    if(descriptor>=0) { length=read(descriptor,info,sizeof(info)); ::close(descriptor); }
    const ssize_t again=readlink(path.c_str(),link,sizeof(link));
    const bool stable=again==n && again>0 && std::memcmp(link,target.data(),n)==0;
    if(!stable) races++;
    std::ostringstream item;
    item<<"{\"fd\":"<<numeric<<",\"target\":"<<quoted(target)<<",\"stable_link\":"<<(stable?"true":"false")<<",\"stat_valid\":"<<(statValid && stable?"true":"false");
    if(statValid && stable) {
      item<<",\"file_type\":\""<<(S_ISCHR(st.st_mode)?"char":S_ISREG(st.st_mode)?"regular":"other")<<'"';
      if(S_ISCHR(st.st_mode)) item<<",\"major\":"<<major(st.st_rdev)<<",\"minor\":"<<minor(st.st_rdev);
    }
    item<<",\"fdinfo_available\":"<<(length>=0 && stable?"true":"false")<<",\"fdinfo_truncated\":"<<(length==ssize_t(sizeof(info))?"true":"false");
    if(length>=0 && stable) item<<",\"fdinfo\":"<<selectedFdInfo(std::string(info,length));
    item<<'}'; matches.push_back(item.str());
  }
  const auto duration=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();
  std::ostringstream out;
  out<<",\"non_atomic_snapshot\":true,\"lease_status_inferred\":false,\"scanned\":"<<scanned<<",\"matched\":"<<matches.size()<<",\"races\":"<<races<<",\"truncated\":"<<(truncated?"true":"false")<<",\"duration_ns\":"<<duration<<",\"fds\":[";
  for(size_t i=0;i<matches.size();i++) { if(i) out<<','; out<<matches[i]; }
  out<<']'; return out.str();
}
} // namespace nadoc_capture
