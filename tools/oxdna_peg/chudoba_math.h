#pragma once
// Chudoba et al., JCTC 2017, DOI 10.1021/acs.jctc.7b00560.
// Shared CPU/CUDA math; nm, kJ/mol, K. Forces are -grad(U).
#include <cmath>
#ifdef __CUDACC__
#define PEG_HD __host__ __device__
#else
#define PEG_HD
#endif
namespace chudoba {
template<class R> struct Vec {
    R x,y,z;
    PEG_HD Vec(R a=0,R b=0,R c=0):x(a),y(b),z(c){}
    PEG_HD Vec operator+(Vec b)const{return Vec(x+b.x,y+b.y,z+b.z);}
    PEG_HD Vec operator-(Vec b)const{return Vec(x-b.x,y-b.y,z-b.z);}
    PEG_HD Vec operator*(R s)const{return Vec(x*s,y*s,z*s);}
};
template<class R> PEG_HD R dot(Vec<R>a,Vec<R>b){return a.x*b.x+a.y*b.y+a.z*b.z;}
template<class R> PEG_HD Vec<R> cross(Vec<R>a,Vec<R>b){return Vec<R>(a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x);}
template<class R> PEG_HD R bond(Vec<R> u,Vec<R>* f){
    R r=sqrt(dot(u,u)), d=r-R(.33);
    f[0]=u*(R(17000)*d/r); f[1]=f[0]*R(-1);
    return R(8500)*d*d;
}
template<class R> PEG_HD R angle(Vec<R> u,Vec<R> v,Vec<R>* f){
    R uu=dot(u,u),vv=dot(v,v),iv=R(1)/sqrt(uu*vv);
    R c=-dot(u,v)*iv, d=c-R(-.6427876096865393263);
    Vec<R> gu=(v*(-iv)-u*(c/uu))*(R(85)*d);
    Vec<R> gv=(u*(-iv)-v*(c/vv))*(R(85)*d);
    f[0]=gu; f[1]=gv-gu; f[2]=gv*R(-1);
    return R(42.5)*d*d;
}
template<class R> PEG_HD R torsion(Vec<R> u,Vec<R> v,Vec<R> w,Vec<R>* f){
    Vec<R> a=cross(u,v),b=cross(v,w);
    R aa=dot(a,a),bb=dot(b,b),iv=R(1)/sqrt(aa*bb);
    R c=dot(a,b)*iv,c2=c*c;
    R du=R(-1.96)+R(.72)*c+R(.33)*(R(12)*c2-R(3))+R(.12)*(R(32)*c2*c-R(16)*c);
    Vec<R> ga=(b*iv-a*(c/aa))*du,gb=(a*iv-b*(c/bb))*du;
    Vec<R> gu=cross(v,ga),gv=cross(ga,u)+cross(w,gb),gw=cross(gb,v);
    f[0]=gu; f[1]=gv-gu; f[2]=gw-gv; f[3]=gw*R(-1);
    return R(1.96)*(R(1)-c)+R(.36)*c2+R(.33)*(R(1)+R(4)*c2*c-R(3)*c)+R(.12)*(R(8)*c2*c2-R(8)*c2+R(2));
}
// Temperature-only coefficients are shared by every pair at a fixed state.
template<class R> struct PairParameters {
    R n,m,sigma,mu,d,norm;
    PEG_HD explicit PairParameters(R temperature) {
        n=8;m=R(54)*pow(R(.9943),temperature);
        sigma=R(.367)+R(.000139)*temperature;
        mu=R(.604)+R(.00029)*temperature;
        if(fabs(temperature-R(270))<R(1e-4)) {m=R(10.74);sigma=R(.4039);mu=R(.6818);}
        if(fabs(temperature-R(396))<R(1e-4)) {m=R(5.94);sigma=R(.4238);mu=R(.7154);}
        if(fabs(temperature-R(422))<R(1e-4)) {m=R(5.24);sigma=R(.4277);mu=R(.7219);}
        if(fabs(temperature-R(450))<R(1e-4)) {m=R(5.09);sigma=R(.4312);mu=R(.7277);}
        d=n-m;
        norm=fabs(d)<R(1e-7) ? n*exp(R(1))*R(1.372) : n*exp(m*log1p(d/m)/d)*R(1.372);
    }
};
template<class R> PEG_HD R pair_with_parameters(R r,const PairParameters<R>&p,R &derivative,bool truncate=true,bool zero_tail=false){
    derivative=0;
    if(truncate && r>=R(.9)) return 0;
    R L=log(p.sigma/r);
    // expm1 retains precision when m approaches n.
    R dd=fabs(p.d)<R(1e-7) ? L : expm1(p.d*L)/p.d;
    R power=exp(p.m*L),z=(r-p.mu)/R(.1064),g=R(.4841)*exp(-z*z);
    derivative=-p.norm*power*(p.m*dd+exp(p.d*L))/r-R(2)*z*g/R(.1064);
    R energy=p.norm*power*dd+g;
    if(zero_tail && r>p.mu && energy<0) {derivative=0;return 0;}
    return energy;
}
template<class R> PEG_HD R pair(R r,R temperature,R &derivative,bool truncate=true,bool zero_tail=false){
    derivative=0;
    if(truncate && r>=R(.9)) return 0;
#ifdef __CUDACC__
    const PairParameters<R> p(temperature);
#else
    // Thread-local cache is invalidated on every temperature change, including
    // replica/state changes. It does not modify any physical parameter.
    static thread_local R last_temperature=temperature;
    static thread_local PairParameters<R> p(temperature);
    if(temperature!=last_temperature) {p=PairParameters<R>(temperature);last_temperature=temperature;}
#endif
    return pair_with_parameters(r,p,derivative,truncate,zero_tail);
}
}
#undef PEG_HD
