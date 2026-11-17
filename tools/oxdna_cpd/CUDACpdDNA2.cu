// Appended to a private, checked copy of upstream's DNA2 CUDA implementation.
#include <fstream>
#include <set>
#include <iomanip>

struct CpdSpringGPU { c_number4 a, b; c_number length, stiffness; };
struct CpdWeldGPU { int first, second; CpdSpringGPU springs[16]; };

__global__ void cpd_inverse(const c_number4 *pos, int *inverse, int n, int *ends, const LR_bonds *bonds) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if(i < n) { inverse[get_particle_index(pos[i])] = i; ends[i]=(bonds[i].n3==P_INVALID || bonds[i].n5==P_INVALID); }
}

__global__ void cpd_welds(const c_number4 *pos, const GPU_quat *quat, c_number4 *forces,
        c_number4 *torques, const int *inverse, const CpdWeldGPU *welds, int count,
        const CUDABox *box, bool update_st, CUDAStressTensor *st, const LR_bonds *bonds,
        c_number4 *audit_forces, c_number4 *audit_torques, bool grooving, bool use_mbf, c_number xmax, c_number finf) {
    int endpoint = blockIdx.x * blockDim.x + threadIdx.x;
    if(endpoint >= count * 2) return;
    CpdWeldGPU weld = welds[endpoint / 2];
    int p = inverse[weld.first], q = inverse[weld.second];
    c_number4 a1,a2,a3,b1,b2,b3;
    get_vectors_from_quat(quat[p],a1,a2,a3);
    get_vectors_from_quat(quat[q],b1,b2,b3);
    c_number4 centre = box->minimum_image(pos[p],pos[q]);
    c_number4 F = make_c_number4(0,0,0,0), T = F;
    bool first = endpoint % 2 == 0;
    for(int k=0;k<16;k++) {
        CpdSpringGPU s = weld.springs[k];
        c_number4 a = a1*s.a.x + a2*s.a.y + a3*s.a.z;
        c_number4 b = b1*s.b.x + b2*s.b.y + b3*s.b.z;
        c_number4 r = centre + b - a;
        c_number distance = _module(r);
        c_number delta = distance-s.length;
        c_number4 f = r*(s.stiffness*delta/distance);
        F += first ? f : -f;
        F.w += .5f*s.stiffness*delta*delta;
        T += first ? _cross(a,f) : -_cross(b,f);
    }
    int i = first ? p : q;
    if(audit_forces) {
        c_number4 AF=F, AT=T, dF=make_c_number4(0,0,0,0);
        int j=first?q:p;
        c_number4 x=first?a1:b1, y=first?a2:b2, z=first?a3:b3;
        c_number4 u=first?b1:a1, v=first?b2:a2, w=first?b3:a3;
        if(bonds[i].n3==j) _bonded_part<true>(pos[j]-pos[i],pos[i],x,y,z,pos[j],u,v,w,dF,AT,grooving,true,use_mbf,xmax,finf);
        if(bonds[i].n5==j) _bonded_part<false>(pos[i]-pos[j],pos[j],u,v,w,pos[i],x,y,z,dF,AT,grooving,true,use_mbf,xmax,finf);
        audit_forces[i]=AF+dF;
        audit_torques[i]=_vectors_transpose_c_number4_product(x,y,z,AT);
    }
    forces[i] += F;
    torques[i] += first ? _vectors_transpose_c_number4_product(a1,a2,a3,T)
                        : _vectors_transpose_c_number4_product(b1,b2,b3,T);
    if(update_st) {
        CUDAStressTensor contribution;
        _update_stress_tensor<true>(contribution,first ? centre : -centre,F);
        st[i] += contribution;
    }
}

class CUDACpdDNA2 : public CpdCudaBase {
    std::string filename;
    std::string audit_file;
    int *partners = nullptr, *inverse = nullptr;
    CpdWeldGPU *device_welds = nullptr;
    int count = 0;
    c_number4 *audit_forces=nullptr, *audit_torques=nullptr;
    void release() {
        if(partners) cudaFree(partners);
        if(inverse) cudaFree(inverse);
        if(device_welds) cudaFree(device_welds);
        if(audit_forces) cudaFree(audit_forces);
        if(audit_torques) cudaFree(audit_torques);
        audit_forces=nullptr; audit_torques=nullptr;
        partners=nullptr; inverse=nullptr; device_welds=nullptr;
    }
public:
    ~CUDACpdDNA2() override { release(); }
    void get_settings(input_file &inp) override {
        input_file dna = inp;
        dna.set_value("interaction_type","DNA2");
        CpdCudaBase::get_settings(dna);
        getInputString(&inp,"cpd_file",filename,1);
        getInputString(&inp,"cpd_cuda_audit_file",audit_file,0);
    }
    void cuda_init(int N) override {
        CpdCudaBase::cuda_init(N);
        release();
        std::ifstream file(filename);
        std::string magic; int version;
        if(!(file>>magic>>version>>count) || magic!="NADOC_CPD" || version!=1 || count<1 || count>N/2)
            throw oxDNAException("Invalid CUDA CPD header");
        std::vector<int> host_partners(N,-1);
        std::vector<CpdWeldGPU> welds(count);
        for(auto &w:welds) {
            int ns;
            if(!(file>>w.first>>w.second>>ns) || ns!=16 || w.first<0 || w.second<0 ||
               w.first>=N || w.second>=N || w.first==w.second ||
               host_partners[w.first]!=-1 || host_partners[w.second]!=-1)
                throw oxDNAException("Invalid CUDA CPD endpoints");
            host_partners[w.first]=w.second; host_partners[w.second]=w.first;
            for(auto &s:w.springs) {
                s.a.w=s.b.w=0;
                if(!(file>>s.a.x>>s.a.y>>s.a.z>>s.b.x>>s.b.y>>s.b.z>>s.length>>s.stiffness) ||
                   !std::isfinite(s.a.x)||!std::isfinite(s.a.y)||!std::isfinite(s.a.z)||
                   !std::isfinite(s.b.x)||!std::isfinite(s.b.y)||!std::isfinite(s.b.z)||
                   !std::isfinite(s.length)||!std::isfinite(s.stiffness)||s.length<=0||s.stiffness<0)
                    throw oxDNAException("Invalid CUDA CPD spring");
            }
        }
        std::string trailing;
        if(file>>trailing) throw oxDNAException("Trailing CUDA CPD records");
        CUDA_SAFE_CALL(cudaMalloc(&partners,N*sizeof(int)));
        CUDA_SAFE_CALL(cudaMalloc(&inverse,N*sizeof(int)));
        CUDA_SAFE_CALL(cudaMalloc(&device_welds,count*sizeof(CpdWeldGPU)));
        CUDA_SAFE_CALL(cudaMemcpy(partners,host_partners.data(),N*sizeof(int),cudaMemcpyHostToDevice));
        CUDA_SAFE_CALL(cudaMemcpy(device_welds,welds.data(),count*sizeof(CpdWeldGPU),cudaMemcpyHostToDevice));
        CUDA_SAFE_CALL(cudaMemcpyToSymbol(cpd_partner,&partners,sizeof(partners)));
        if(!audit_file.empty()) {
            CUDA_SAFE_CALL(cudaMalloc(&audit_forces,N*sizeof(c_number4)));
            CUDA_SAFE_CALL(cudaMalloc(&audit_torques,N*sizeof(c_number4)));
            CUDA_SAFE_CALL(cudaMemset(audit_forces,0,N*sizeof(c_number4)));
            CUDA_SAFE_CALL(cudaMemset(audit_torques,0,N*sizeof(c_number4)));
        }
        OX_LOG(Logger::LOG_INFO,"NADOC_CPD_CUDA_V1: %d permanent welds, sorting-safe",count);
    }
    void compute_forces(CUDABaseList *lists,c_number4 *pos,GPU_quat *quat,c_number4 *forces,
            c_number4 *torques,LR_bonds *bonds,CUDABox *box) override {
        if(_d_is_strand_end==nullptr) _init_strand_ends(bonds);
        cpd_inverse<<<(_N+127)/128,128>>>(pos,inverse,_N,_d_is_strand_end,bonds);
        CpdCudaBase::compute_forces(lists,pos,quat,forces,torques,bonds,box);
        if(audit_forces) {
            CUDA_SAFE_CALL(cudaMemset(audit_forces,0,_N*sizeof(c_number4)));
            CUDA_SAFE_CALL(cudaMemset(audit_torques,0,_N*sizeof(c_number4)));
        }
        cpd_welds<<<(2*count+127)/128,128>>>(pos,quat,forces,torques,inverse,device_welds,count,box,_update_st,_d_st,bonds,audit_forces,audit_torques,_grooving,_use_mbf,_mbf_xmax,_mbf_finf);
        CUT_CHECK_ERROR("CPD CUDA forces");
        if(!audit_file.empty()) {
            std::vector<c_number4> hp(_N),hf(_N),ht(_N),af(_N),at(_N);
            std::vector<GPU_quat> hq(_N);
            CUDA_SAFE_CALL(cudaMemcpy(hp.data(),pos,_N*sizeof(c_number4),cudaMemcpyDeviceToHost));
            CUDA_SAFE_CALL(cudaMemcpy(hf.data(),forces,_N*sizeof(c_number4),cudaMemcpyDeviceToHost));
            CUDA_SAFE_CALL(cudaMemcpy(ht.data(),torques,_N*sizeof(c_number4),cudaMemcpyDeviceToHost));
            CUDA_SAFE_CALL(cudaMemcpy(hq.data(),quat,_N*sizeof(GPU_quat),cudaMemcpyDeviceToHost));
            CUDA_SAFE_CALL(cudaMemcpy(af.data(),audit_forces,_N*sizeof(c_number4),cudaMemcpyDeviceToHost));
            CUDA_SAFE_CALL(cudaMemcpy(at.data(),audit_torques,_N*sizeof(c_number4),cudaMemcpyDeviceToHost));
            std::ofstream out(audit_file);
            out<<std::setprecision(17);
            for(int i=0;i<_N;i++) out<<get_particle_index_host(hp[i])<<" "
                <<hp[i].x<<" "<<hp[i].y<<" "<<hp[i].z<<" "
                <<hq[i].x<<" "<<hq[i].y<<" "<<hq[i].z<<" "<<hq[i].w<<" "
                <<hf[i].x<<" "<<hf[i].y<<" "<<hf[i].z<<" "
                <<ht[i].x<<" "<<ht[i].y<<" "<<ht[i].z<<" "
                <<af[i].x<<" "<<af[i].y<<" "<<af[i].z<<" "
                <<at[i].x<<" "<<at[i].y<<" "<<at[i].z<<"\n";
        }
    }
};
extern "C" BaseInteraction *make_CUDACpdDNA2() { return new CUDACpdDNA2(); }
extern "C" BaseInteraction *make_interaction() { return new CUDACpdDNA2(); }
