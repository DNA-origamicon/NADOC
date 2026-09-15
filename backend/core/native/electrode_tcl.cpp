// Same EW3DC, harmonic confinement and site springs as the reference Tcl callback.
// Tcl stubs keep this extension independent of the NAMD executable's Tcl linkage.
#include <tcl.h>
#include <array>
#include <vector>
#include <cmath>

static int forces(ClientData, Tcl_Interp *ip, int argc, Tcl_Obj *const argv[]) {
    if (argc != 10) { Tcl_WrongNumArgs(ip,1,argv,"coords charges mobile axis coefficient low high wall_k sites"); return TCL_ERROR; }
    int axis, nc, nm, ns;
    double coefficient, low, high, wall;
    Tcl_Obj **charges, **mobile, **sites;
    if (Tcl_GetIntFromObj(ip,argv[4],&axis)!=TCL_OK || axis<0 || axis>2 ||
        Tcl_GetDoubleFromObj(ip,argv[5],&coefficient)!=TCL_OK ||
        Tcl_GetDoubleFromObj(ip,argv[6],&low)!=TCL_OK ||
        Tcl_GetDoubleFromObj(ip,argv[7],&high)!=TCL_OK ||
        Tcl_GetDoubleFromObj(ip,argv[8],&wall)!=TCL_OK ||
        Tcl_ListObjGetElements(ip,argv[2],&nc,&charges)!=TCL_OK || nc%2 ||
        Tcl_ListObjGetElements(ip,argv[3],&nm,&mobile)!=TCL_OK ||
        Tcl_ListObjGetElements(ip,argv[9],&ns,&sites)!=TCL_OK || ns%2) return TCL_ERROR;
    struct Atom { Tcl_Obj *id=nullptr; std::array<double,3> x{}, f{}; };
    std::vector<Atom> atoms;
    auto get=[&](Tcl_Obj *id)->Atom* {
        int index;
        if(Tcl_GetIntFromObj(ip,id,&index)!=TCL_OK || index<1 || index>100000000) return nullptr;
        if(static_cast<size_t>(index)>=atoms.size()) atoms.resize(index+1);
        Atom &a=atoms[index];
        if(!a.id) {
            Tcl_Obj *value=Tcl_ObjGetVar2(ip,argv[1],id,TCL_LEAVE_ERR_MSG);
            Tcl_Obj **v; int n;
            if(!value || Tcl_ListObjGetElements(ip,value,&n,&v)!=TCL_OK || n!=3) return nullptr;
            for(int j=0;j<3;j++) if(Tcl_GetDoubleFromObj(ip,v[j],&a.x[j])!=TCL_OK || !std::isfinite(a.x[j])) return nullptr;
            a.id=id;
        }
        return &a;
    };
    double dipole=0, energy=0;
    for(int i=0;i<nc;i+=2) {
        Atom *a=get(charges[i]); double q;
        if(!a || Tcl_GetDoubleFromObj(ip,charges[i+1],&q)!=TCL_OK) return TCL_ERROR;
        dipole+=q*a->x[axis];
    }
    energy=coefficient*dipole*dipole;
    for(int i=0;i<nc;i+=2) {
        Atom *a=get(charges[i]); double q;
        if(!a || Tcl_GetDoubleFromObj(ip,charges[i+1],&q)!=TCL_OK) return TCL_ERROR;
        a->f[axis]-=2*coefficient*q*dipole;
    }
    for(int i=0;i<nm;i++) {
        Atom *a=get(mobile[i]); if(!a) return TCL_ERROR;
        double z=a->x[axis],delta=z<low?z-low:z>high?z-high:0;
        a->f[axis]-=wall*delta; energy+=.5*wall*delta*delta;
    }
    for(int i=0;i<ns;i+=2) {
        Atom *a=get(sites[i]); Tcl_Obj **ref; int n; double k;
        if(!a || Tcl_ListObjGetElements(ip,sites[i+1],&n,&ref)!=TCL_OK || n!=4 || Tcl_GetDoubleFromObj(ip,ref[3],&k)!=TCL_OK) return TCL_ERROR;
        for(int j=0;j<3;j++) {
            double x;if(Tcl_GetDoubleFromObj(ip,ref[j],&x)!=TCL_OK) return TCL_ERROR;
            double d=a->x[j]-x;a->f[j]-=k*d;energy+=.5*k*d*d;
        }
    }
    Tcl_CmdInfo command;
    if(!Tcl_GetCommandInfo(ip,"addforce",&command) || !command.objProc) return TCL_ERROR;
    Tcl_Obj *name=Tcl_NewStringObj("addforce",-1);Tcl_IncrRefCount(name);
    for(auto &a:atoms) if(a.id) {
        Tcl_Obj *v[3]={Tcl_NewDoubleObj(a.f[0]),Tcl_NewDoubleObj(a.f[1]),Tcl_NewDoubleObj(a.f[2])};
        Tcl_Obj *list=Tcl_NewListObj(3,v);Tcl_IncrRefCount(list);
        Tcl_Obj *args[3]={name,a.id,list};
        int rc=command.objProc(command.objClientData,ip,3,args);
        Tcl_DecrRefCount(list);
        if(rc!=TCL_OK){Tcl_DecrRefCount(name);return rc;}
    }
    Tcl_DecrRefCount(name);
    Tcl_Obj *args[2]={Tcl_NewStringObj("addenergy",-1),Tcl_NewDoubleObj(energy)};
    for(auto o:args)Tcl_IncrRefCount(o);
    int rc=Tcl_EvalObjv(ip,2,args,0);
    for(auto o:args)Tcl_DecrRefCount(o);
    return rc;
}
extern "C" int Electrodenative_Init(Tcl_Interp *ip) {
    if(!Tcl_InitStubs(ip,"8.6",0)) return TCL_ERROR;
    Tcl_CreateObjCommand(ip,"nadoc_electrode_forces",forces,nullptr,nullptr);
    return Tcl_PkgProvide(ip,"electrode_native","1.0");
}
