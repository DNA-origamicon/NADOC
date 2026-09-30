#pragma once
// Render-thread staging: bounded CPU batches and bytes, never wait on a fence.
// Prepared inputs are immutable and built by the scene parsing worker.
struct ResidentRepresentation {
    std::array<GLuint,4> buffers{};
    std::array<GLsizei,4> counts{};
    std::shared_ptr<PreparedRepresentation> prepared;
    Coloring color=Coloring::strand;
    ~ResidentRepresentation(){glDeleteBuffers(4,buffers.data());}
};
class StagedRepresentation {
    std::shared_ptr<ResidentRepresentation> result_;
    size_t channel_=0,offset_=0,done_=0,total_=0;
    bool allocated_=false;
    double idsMs_=0,driverMs_=0;
    GLsync fence_=nullptr;
    template<class V,class Id>
    void batch(const std::vector<V>& values,Id id,size_t& bytes) {
        const auto& records=result_->prepared->records[channel_];
        glBindBuffer(GL_ARRAY_BUFFER,result_->buffers[channel_]);
        const auto begin=std::chrono::steady_clock::now();
        if(!allocated_){
            glBufferData(GL_ARRAY_BUFFER,values.size()*sizeof(V),nullptr,GL_STATIC_DRAW);
            driverMs_+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-begin).count();
            if(glGetError()!=GL_NO_ERROR)throw std::runtime_error("Insufficient GPU storage for representation");
            allocated_=true;
            return; // Allocation is a separate work unit; check time before copying.
        }
        const size_t count=std::min(size_t(256),values.size()-offset_);
        std::array<V,256> chunk;
        for(size_t i=0;i<count;++i){chunk[i]=values[offset_+i];
            chunk[i].objectId=id(*records[offset_+i].identity);
            chunk[i].color=records[offset_+i].colors->get(result_->color);
        }
        const auto prepared=std::chrono::steady_clock::now();
        idsMs_+=std::chrono::duration<double,std::milli>(prepared-begin).count();
        if(count)glBufferSubData(GL_ARRAY_BUFFER,offset_*sizeof(V),count*sizeof(V),chunk.data());
        if(glGetError()!=GL_NO_ERROR)throw std::runtime_error("Representation GPU upload failed");
        driverMs_+=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-prepared).count();
        offset_+=count;done_+=count*sizeof(V);bytes+=count*sizeof(V);
        if(offset_==values.size()){++channel_;offset_=0;allocated_=false;}
    }
 public:
    ~StagedRepresentation(){cancel();}
    bool pending()const{return bool(result_);}
    double progress()const{return total_?double(done_)/total_:0;}
    void cancel(){if(fence_)glDeleteSync(fence_);fence_=nullptr;result_.reset();channel_=offset_=done_=total_=0;allocated_=false;}
    void start(std::shared_ptr<PreparedRepresentation> prepared,Coloring color){
        cancel();result_=std::make_shared<ResidentRepresentation>();result_->prepared=std::move(prepared);result_->color=color;
        auto& p=*result_->prepared;
        result_->counts={GLsizei(p.points.size()),GLsizei(p.cylinders.size()),GLsizei(p.halves.size()),GLsizei(p.boxes.size())};
        total_=p.bytes();glGenBuffers(4,result_->buffers.data());
    }
    template<class Id> std::shared_ptr<ResidentRepresentation> poll(Id id,double budgetMs=1.0){
        if(!result_)return {};
        if(fence_){const auto status=glClientWaitSync(fence_,0,0);
            if(status==GL_WAIT_FAILED)throw std::runtime_error("Representation upload fence failed");
            if(status==GL_TIMEOUT_EXPIRED)return {};
            glDeleteSync(fence_);fence_=nullptr;return std::exchange(result_,{});
        }
        const auto start=std::chrono::steady_clock::now();size_t bytes=0;idsMs_=driverMs_=0;
        auto& p=*result_->prepared;
        constexpr size_t maxBatchBytes=256*std::max({sizeof(Vertex),sizeof(Cylinder),sizeof(Box)});
        while(channel_<4 && bytes+maxBatchBytes<=256*1024 && std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count()<budgetMs){
            switch(channel_){case 0:batch(p.points,id,bytes);break;case 1:batch(p.cylinders,id,bytes);break;
                case 2:batch(p.halves,id,bytes);break;case 3:batch(p.boxes,id,bytes);break;}
        }
        if(idsMs_+driverMs_>2)nadoc_vr::TraceRecord{}<<"VR_UPLOAD_TRACE epoch_ms="<<std::fixed
            <<std::chrono::duration<double,std::milli>(std::chrono::system_clock::now().time_since_epoch()).count()
            <<" ids_ms="<<idsMs_<<" driver_ms="<<driverMs_<<" bytes="<<bytes<<'\n';
        if(channel_==4){fence_=glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);
            if(!fence_)throw std::runtime_error("Cannot create representation upload fence");
            glFlush();}
        return {};
    }
};
