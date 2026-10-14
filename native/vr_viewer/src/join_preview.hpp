#pragma once
#include <glm/glm.hpp>
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <fstream>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace nadoc_vr {
struct JoinSite { bool moving=false; glm::vec3 position{},normal{}; };
struct JoinSegment { glm::vec3 first{},second{}; };
struct JoinCell {
    int x=0,y=0,z=0;
    bool operator==(const JoinCell&) const=default;
};
struct JoinCellHash {
    size_t operator()(JoinCell c) const {
        return size_t(uint32_t(c.x)*73856093U)^size_t(uint32_t(c.y)*19349663U)^size_t(uint32_t(c.z)*83492791U);
    }
};
struct JoinSiteIndex {
    static constexpr float reachNm=3.F;
    std::vector<JoinSite> moving,fixed;
    std::unordered_map<JoinCell,std::vector<size_t>,JoinCellHash> cells;
    static JoinCell cell(glm::vec3 p) {return {int(std::floor(p.x/reachNm)),int(std::floor(p.y/reachNm)),int(std::floor(p.z/reachNm))};}
    void add(JoinSite s) {
        if(s.moving)moving.push_back(s);
        else {cells[cell(s.position)].push_back(fixed.size());fixed.push_back(s);}
    }
};
struct JoinFeedback {
    uint64_t sequence=0,toolSequence=0,requestSequence=0;
    bool valid=false;
    size_t connections=0;
    std::string status,message;
    std::vector<JoinSegment> bridges;
    std::shared_ptr<const JoinSiteIndex> sites;
    std::shared_ptr<const std::string> siteRecord;
};
// The shared stroke font is ASCII. Decode the bounded UTF-8 transport first,
// retaining words and replacing unsupported glyphs without discarding feedback.
inline std::optional<std::string> joinMessage(const std::string& token) {
    std::string bytes;
    auto hex=[](char c){return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;};
    for(size_t i=0;i<token.size();++i) {
        unsigned char value=static_cast<unsigned char>(token[i]);
        if(value=='%') {
            if(i+2>=token.size() || hex(token[i+1])<0 || hex(token[i+2])<0)return {};
            value=static_cast<unsigned char>(hex(token[i+1])*16+hex(token[i+2]));i+=2;
        }
        if(value<32 || value==127)return {};
        bytes+=char(value);if(bytes.size()>2048)return {};
    }
    std::string result;
    for(size_t i=0;i<bytes.size();++i) {
        const auto value=static_cast<unsigned char>(bytes[i]);
        if(value<128)result+=char(value);
        else if(bytes.compare(i,3,"\xe2\x80\xa6")==0){result+="...";i+=2;}
        else if(value>=192)result+=' ';
        if(result.size()>1536)return {};
    }
    return result;
}
inline std::shared_ptr<JoinFeedback> parseJoinFeedback(const std::string& text,const std::shared_ptr<const JoinFeedback>& previous={}) {
    if(text.size()>2*1024*1024)return {};
    std::istringstream in(text);std::string magic;int valid=0;size_t nb=0,ns=0;
    auto result=std::make_shared<JoinFeedback>();
    if(!(in>>magic>>result->sequence>>result->toolSequence>>result->requestSequence>>result->status>>valid>>result->connections>>nb>>ns>>result->message) ||
       magic!="NADOC_JOIN_1" || !result->sequence || !result->toolSequence || valid<0 || valid>1 || nb>128 || ns>8192 || result->connections>1000000 || result->message.size()>8192)return {};
    static constexpr std::array<const char*,9> statuses{"ready","checking","valid","invalid","applying","applied","cancelled","failed","idle"};
    if(std::find(statuses.begin(),statuses.end(),result->status)==statuses.end())return {};
    const auto message=joinMessage(result->message);if(!message)return {};result->message=*message;
    result->valid=valid==1;
    auto vector=[&](glm::vec3& p) {return bool(in>>p.x>>p.y>>p.z)&&std::isfinite(p.x)&&std::isfinite(p.y)&&std::isfinite(p.z)&&glm::all(glm::lessThanEqual(glm::abs(p),glm::vec3(1e9F)));};
    result->bridges.resize(nb);
    for(auto& b:result->bridges)if(!vector(b.first)||!vector(b.second))return {};
    if(ns) {
        const auto offset=in.tellg();if(offset<0)return {};
        const auto records=text.substr(size_t(offset));
        if(previous && previous->sites && ns==previous->sites->moving.size()+previous->sites->fixed.size() && previous->siteRecord && *previous->siteRecord==records) {
            result->sites=previous->sites;result->siteRecord=previous->siteRecord;return result;
        }
        result->siteRecord=std::make_shared<const std::string>(records);
        auto sites=std::make_shared<JoinSiteIndex>();
        for(size_t i=0;i<ns;++i) {
            JoinSite site;int moving;
            if(!(in>>moving) || moving<0 || moving>1 || !vector(site.position) || !vector(site.normal))return {};
            const float length=glm::length(site.normal);if(length<.5F || length>1.5F)return {};
            site.normal/=length;site.moving=moving==1;sites->add(site);
        }
        result->sites=std::move(sites);
    }
    std::string extra;if(in>>extra)return {};
    return result;
}
// Disk reads, parsing, and site indexing never enter the headset frame loop.
// The browser publishes atomically; the consumer adopts only its latest snapshot.
class JoinFeedbackReader {
    std::mutex mutex_;std::condition_variable wake_;bool stopped_=false;
    std::string path_;std::atomic<std::shared_ptr<const JoinFeedback>> latest_;
    std::thread worker_;
public:
    JoinFeedbackReader():worker_([this] {
        uint64_t sequence=0;std::string previousPath;
        std::shared_ptr<const JoinSiteIndex> catalog;uint64_t catalogTool=0;
        for(;;) {
            std::string path;
            {std::unique_lock lock(mutex_);wake_.wait_for(lock,std::chrono::milliseconds(50),[&]{return stopped_;});if(stopped_)return;path=path_;}
            if(path.empty())continue;
            if(path!=previousPath){sequence=0;previousPath=path;}
            std::ifstream in(path,std::ios::binary|std::ios::ate);if(!in)continue;
            const auto bytes=in.tellg();if(bytes<0 || bytes>2*1024*1024)continue;
            std::string text(size_t(bytes),'\0');in.seekg(0);if(!in.read(text.data(),bytes))continue;
            const auto end=text.find('\n');std::istringstream header(text.substr(0,end));std::string magic;uint64_t incoming=0;
            if(!(header>>magic>>incoming) || incoming<=sequence)continue;
            auto feedback=parseJoinFeedback(text,latest_.load());if(!feedback)continue;
            if(feedback->sites){catalog=feedback->sites;catalogTool=feedback->toolSequence;}
            else if(catalogTool==feedback->toolSequence)feedback->sites=catalog;
            sequence=feedback->sequence;latest_.store(std::move(feedback));
        }
    }){}
    ~JoinFeedbackReader(){{std::lock_guard lock(mutex_);stopped_=true;}wake_.notify_one();worker_.join();}
    void setPath(const std::string& path){std::lock_guard lock(mutex_);path_=path;}
    std::shared_ptr<const JoinFeedback> latest() const {return latest_.load();}
};
class JoinPreview {
public:
    static constexpr size_t maximumComparisons=4096,maximumMovingSites=256,maximumHints=32;
    std::shared_ptr<const JoinFeedback> feedback;
    std::shared_ptr<const JoinSiteIndex> sites;
    std::array<JoinSegment,maximumHints> hints{};
    size_t hintCount=0,comparisons=0;
    uint64_t minimumSequence=0;
    glm::mat4 hintTransform{0};
    const JoinSiteIndex* hintSites=nullptr;
    void clear() {if(feedback)minimumSequence=std::max(minimumSequence,feedback->sequence);feedback.reset();sites.reset();hintSites=nullptr;hintCount=comparisons=0;}
    bool accept(std::shared_ptr<const JoinFeedback> next,uint64_t toolSequence,uint64_t transformSequence) {
        if(!next || next->sequence<=minimumSequence || (feedback && next->sequence<=feedback->sequence) || next->toolSequence!=toolSequence || next->requestSequence>transformSequence)return false;
        if(next->sites)sites=next->sites;
        feedback=std::move(next);return true;
    }
    bool ready(uint64_t toolSequence,uint64_t transformSequence) const {
        return feedback && feedback->toolSequence==toolSequence && feedback->requestSequence==transformSequence && feedback->valid && feedback->status=="valid" && feedback->connections>0;
    }
    void update(const glm::mat4& transform) {
        if(hintSites==sites.get() && hintTransform==transform)return;
        hintSites=sites.get();hintTransform=transform;
        hintCount=comparisons=0;if(!sites)return;
        std::array<size_t,maximumHints> used{};
        for(size_t moving=0;moving<std::min(maximumMovingSites,sites->moving.size()) && comparisons<maximumComparisons && hintCount<maximumHints;++moving) {
            const size_t siteIndex=moving*sites->moving.size()/std::min(maximumMovingSites,sites->moving.size());
            const auto& site=sites->moving[siteIndex];const glm::vec3 p=glm::vec3(transform*glm::vec4(site.position,1)),normal=glm::mat3(transform)*site.normal;
            const auto cell=JoinSiteIndex::cell(p);float best=JoinSiteIndex::reachNm;size_t chosen=sites->fixed.size();
            for(int x=-1;x<=1;++x)for(int y=-1;y<=1;++y)for(int z=-1;z<=1;++z) {
                const auto found=sites->cells.find({cell.x+x,cell.y+y,cell.z+z});if(found==sites->cells.end())continue;
                for(size_t index:found->second) {
                    if(comparisons>=maximumComparisons)break;
                    ++comparisons;if(std::find(used.begin(),used.begin()+hintCount,index)!=used.begin()+hintCount)continue;
                    const auto& fixed=sites->fixed[index];const auto delta=p-fixed.position;const float distance=glm::length(delta);
                    if(distance<.3F || distance>best || glm::dot(normal,fixed.normal)>-.25F)continue;
                    if(glm::dot(delta,fixed.normal)<.15F*distance || glm::dot(delta,normal)>-.15F*distance)continue;
                    chosen=index;best=distance;
                }
            }
            if(chosen<sites->fixed.size()) {used[hintCount]=chosen;hints[hintCount++]={sites->fixed[chosen].position,p};}
        }
    }
};
}
