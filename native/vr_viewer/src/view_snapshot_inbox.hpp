#pragma once
// Linux local transport. One receiving packet + one pending packet;
// the render thread only takes ownership, never performs socket I/O.
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iomanip>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <poll.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace nadoc_vr {
class ViewSnapshotInbox {
    int listener_=-1;
    bool display_=true;
    std::atomic<bool> stopping_{false}, received_{false};
    std::mutex mutex_;
    std::condition_variable available_;
    std::optional<std::string> pending_;
    std::thread worker_;
    bool readExact(int fd, char* data, size_t bytes) {
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(2);
        while(bytes && !stopping_ && std::chrono::steady_clock::now()<deadline){
            pollfd p{fd,POLLIN,0};
            if(::poll(&p,1,50)<=0)continue;
            const auto n=::recv(fd,data,bytes,MSG_DONTWAIT);
            if(n<=0)return false;
            data+=n;bytes-=size_t(n);
        }
        return bytes==0;
    }
    void receive(int fd) {
        ucred peer{};socklen_t n=sizeof(peer);
        if(getsockopt(fd,SOL_SOCKET,SO_PEERCRED,&peer,&n)!=0 || peer.uid!=getuid())return;
        unsigned char header[4];
        if(!readExact(fd,reinterpret_cast<char*>(header),4))return;
        uint32_t size=0;for(int i=0;i<4;++i)size|=uint32_t(header[i])<<(8*i);
        if(size<(display_?48U:1U) || size>256U*1024U*1024U)return;
        std::string packet(size,'\0');
        if(!readExact(fd,packet.data(),packet.size()) || (display_ && packet.compare(0,8,"NADOCVT1")!=0))return;
        {std::unique_lock<std::mutex> lock(mutex_);
            if(display_ && !available_.wait_for(lock,std::chrono::seconds(2),[this]{return !pending_ || stopping_;}))return;
            if(stopping_)return;
            pending_=std::move(packet);received_=true;}
        const char ack=1;::send(fd,&ack,1,MSG_NOSIGNAL);
    }
public:
    explicit ViewSnapshotInbox(const std::string& path,bool display=true):display_(display) {
        const char* enabled=std::getenv("NADOC_VR_VIEW_IPC");
        if(enabled && std::string(enabled)=="0")return;
        uint64_t hash=14695981039346656037ULL;
        for(unsigned char c:path){hash^=c;hash*=1099511628211ULL;}
        std::ostringstream name;name<<"nadoc-view-"<<getuid()<<'-'<<std::hex<<std::setw(16)<<std::setfill('0')<<hash;
        sockaddr_un address{};address.sun_family=AF_UNIX;
        const auto key=name.str();std::memcpy(address.sun_path+1,key.data(),key.size());
        listener_=::socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0);
        if(listener_<0)return;
        if(::bind(listener_,reinterpret_cast<sockaddr*>(&address),offsetof(sockaddr_un,sun_path)+1+key.size()) || ::listen(listener_,2)){
            ::close(listener_);listener_=-1;return;
        }
        worker_=std::thread([this]{
            while(!stopping_){
                pollfd p{listener_,POLLIN,0};if(::poll(&p,1,50)<=0)continue;
                int fd=::accept4(listener_,nullptr,nullptr,SOCK_CLOEXEC);
                if(fd<0)continue;
                try{receive(fd);}catch(const std::exception&){}
                ::close(fd);
            }
        });
    }
    ~ViewSnapshotInbox(){stopping_=true;available_.notify_all();if(worker_.joinable())worker_.join();if(listener_>=0)::close(listener_);}
    bool received() const{return received_;}
    std::optional<std::string> take(){std::lock_guard<std::mutex> lock(mutex_);auto out=std::move(pending_);pending_.reset();available_.notify_one();return out;}
};
}
