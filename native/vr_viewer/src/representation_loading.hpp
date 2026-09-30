#pragma once
// Included after SceneData/loadScene. CPU parsing never uses the GL context.
class RepresentationLoading {
 public:
    bool enabled=false,pending=false;
    bool lightweight=false;
    unsigned slowFrames=0;
    double timingWindowMs=0;
    double nominalPeriodMs=0;
    StartupLoading popup;
    std::chrono::steady_clock::time_point lastFrame=std::chrono::steady_clock::now();
    void frameTiming(double,double periodMs){
        const auto now=std::chrono::steady_clock::now();
        const double elapsedMs=std::chrono::duration<double,std::milli>(now-lastFrame).count();lastFrame=now;
        recordFrameGap(elapsedMs,periodMs);
    }
    void recordFrameGap(double elapsedMs,double periodMs){
        // SteamVR can lengthen predictedDisplayPeriod during reprojection.
        // Preserve the observed display cadence instead of treating half-rate
        // delivery as a new healthy frame budget.
        if(periodMs>0 && (nominalPeriodMs==0 || periodMs<nominalPeriodMs))nominalPeriodMs=periodMs;
        if(nominalPeriodMs>0)periodMs=nominalPeriodMs;
        if(!pending){lightweight=false;slowFrames=0;timingWindowMs=0;return;}
        timingWindowMs+=elapsedMs;
        if(timingWindowMs>1000){timingWindowMs=elapsedMs;slowFrames=0;}
        if(elapsedMs>periodMs*1.5)++slowFrames;
        if(slowFrames>=3)lightweight=true;
    }
    void render(const glm::mat4& vp,const XrPosef& head){
        if(!pending){popup.active=false;popup.anchored=false;return;}
        popup.active=true;popup.percent=int(percent);popup.phase=phase;
        std::ostringstream text;text<<std::fixed<<std::setprecision(1)<<percent<<"% "<<detail;
        popup.detail=text.str();popup.render(vp,head,true);
    }
    uint64_t sequence=0,generation=0,parseSequence=0;
    Representation target=Representation::full;
    Coloring color=Coloring::strand;
    double percent=0,visibleUntil=0;
    std::string eventPath,phase,detail;
    std::shared_ptr<std::atomic<double>> parseProgress=std::make_shared<std::atomic<double>>(75);
    std::future<SceneData> parsed;
    std::optional<SceneData> candidate;
    SceneRetirement retired;
    void retireCandidate(){if(candidate){retired.retire(std::move(*candidate));candidate.reset();}}
    void start(Representation rep,Coloring coloring,uint64_t revision) {
        if(pending && target==rep && color==coloring && generation==revision)return;
        target=rep;color=coloring;generation=revision;++sequence;percent=0;
        lightweight=false;slowFrames=0;timingWindowMs=0;pending=true;phase="loading";detail="Preparing";retireCandidate();
        const auto path=eventPath+".repr-request";
        std::ofstream output(path+".next");
        output << "NADOCVR_REP_REQUEST 1 " << sequence << ' ' << representationName(rep) << ' ' << generation << '\n';
        output.close();
        if(!output || std::rename((path+".next").c_str(),path.c_str())!=0)fail("Cannot request representation");
    }
    void fail(const std::string& message){phase="error";detail=message;pending=false;percent=-1;visibleUntil=glfwGetTime()+30;}
    void cancel(){
        ++sequence;pending=false;retireCandidate();visibleUntil=0;phase.clear();
        const auto path=eventPath+".repr-request";
        std::ofstream output(path+".next");
        output<<"NADOCVR_REP_REQUEST 1 "<<sequence<<" cancel "<<generation<<'\n';output.close();
        if(output)(void)std::rename((path+".next").c_str(),path.c_str());
    }
    void poll(glm::vec3 center,float scale) {
        if(retired.full())return; // Backpressure: retain one future, never block the XR thread.
        if(parsed.valid()) {
            if(parseSequence==sequence)percent=std::max(percent,parseProgress->load());
            if(parsed.wait_for(std::chrono::seconds(0))==std::future_status::ready) {
                try {
                    auto result=parsed.get();
                    if(parseSequence==sequence && pending) {
                        candidate=std::move(result);percent=96;phase="upload";detail="Preparing display";
                    } else retired.retire(std::move(result));
                } catch(const std::exception& e){if(parseSequence==sequence)fail(e.what());}
            }
        }
        if(!pending || candidate || parsed.valid() || phase=="waiting")return;
        std::ifstream input(eventPath+".repr-status");
        std::string magic,rep,status;int version=0;uint64_t seq=0,gen=0,records=0;double value=0;
        if(!(input>>magic>>version>>seq>>gen>>rep>>status>>value>>records) || magic!="NADOCVR_REP_STATUS" || version!=1 || seq!=sequence || gen!=generation || rep!=representationName(target))return;
        std::string message;std::getline(input,message);std::getline(input,message);
        if(status=="error"){fail(message);return;}
        if(!std::isfinite(value) || value<0 || value>75)return;
        percent=std::max(percent,value);detail=message;
        if(status=="ready") {
            phase="parsing";parseSequence=sequence;parseProgress->store(75);
            const auto path=eventPath+".repr-"+std::to_string(sequence);
            parsed=std::async(std::launch::async,[path,center,scale,records,progress=parseProgress] {
                return loadScene(path,std::make_pair(center,scale),[progress,records](size_t count){
                    progress->store(75+20*std::min(1.0,double(count)/std::max(1.0,double(records))));
                });
            });
        }
    }
    std::optional<std::pair<float,std::string>> button(const std::string& action) const {
        if(!enabled || action!="repr:"+std::to_string(static_cast<int>(target)) || (!pending && glfwGetTime()>visibleUntil))return {};
        std::ostringstream label;
        if(phase=="error")label<<"FAILED - SELECT TO RETRY";
        else label<<std::fixed<<std::setprecision(1)<<percent<<"% "<<(percent>=100?"READY":phase=="parsing"?"READING":phase=="waiting"?"APPLYING":"LOADING");
        return std::make_pair(float(std::max(0.0,percent)/100),label.str());
    }
};
