// NADOC experimental direct-array EW3DC/wall/spring bridge for GlobalMasterTcl.
// One Tcl call per step; no per-atom Tcl coordinate or force objects.
int GlobalMasterTcl::Tcl_nadoc_electrode(ClientData data, Tcl_Interp *ip,
                                      int argc, Tcl_Obj *const argv[]) {
  if (argc != 9 && argc != 10) { Tcl_WrongNumArgs(ip,1,argv,"charges mobile axis coefficient low high wall_k sites ?audit?"); return TCL_ERROR; }
  int audit=0;
  if(argc==10 && Tcl_GetBooleanFromObj(ip,argv[9],&audit)!=TCL_OK)return TCL_ERROR;
  int axis,nc,nm,ns; double coefficient,low,high,wall;
  Tcl_Obj **charges,**mobile,**sites;
  if (Tcl_GetIntFromObj(ip,argv[3],&axis)!=TCL_OK || axis<0 || axis>2 ||
      Tcl_GetDoubleFromObj(ip,argv[4],&coefficient)!=TCL_OK ||
      Tcl_GetDoubleFromObj(ip,argv[5],&low)!=TCL_OK ||
      Tcl_GetDoubleFromObj(ip,argv[6],&high)!=TCL_OK ||
      Tcl_GetDoubleFromObj(ip,argv[7],&wall)!=TCL_OK ||
      Tcl_ListObjGetElements(ip,argv[1],&nc,&charges)!=TCL_OK || nc%2 ||
      Tcl_ListObjGetElements(ip,argv[2],&nm,&mobile)!=TCL_OK ||
      Tcl_ListObjGetElements(ip,argv[8],&ns,&sites)!=TCL_OK || ns%2) return TCL_ERROR;
  auto *self=static_cast<GlobalMasterTcl*>(data);
  struct Atom { bool present=false,touched=false; std::array<double,3> x{},f{}; };
  std::vector<Atom> atoms;
  auto pos=self->getAtomPositionBegin();
  for(auto id=self->getAtomIdBegin();id!=self->getAtomIdEnd();++id,++pos) {
    if (*id<0) return TCL_ERROR;
    const size_t n=static_cast<size_t>(*id)+1;
    if(n>=atoms.size()) atoms.resize(n+1);
    atoms[n].present=true;
    atoms[n].x={pos->x,pos->y,pos->z};
  }
  auto get=[&](Tcl_Obj *id)->Atom* {
    int i;
    if(Tcl_GetIntFromObj(ip,id,&i)!=TCL_OK || i<1 || static_cast<size_t>(i)>=atoms.size() || !atoms[i].present) {
      Tcl_SetObjResult(ip,Tcl_NewStringObj("NADOC: requested electrode atom coordinates unavailable",-1));return nullptr;
    }
    atoms[i].touched=true; return &atoms[i];
  };
  double dipole=0,energy=0;
  for(int i=0;i<nc;i+=2) {
    auto *a=get(charges[i]);double q;
    if(!a || Tcl_GetDoubleFromObj(ip,charges[i+1],&q)!=TCL_OK)return TCL_ERROR;
    dipole+=q*a->x[axis];
  }
  energy=coefficient*dipole*dipole;
  for(int i=0;i<nc;i+=2) {
    auto *a=get(charges[i]);double q;
    if(!a || Tcl_GetDoubleFromObj(ip,charges[i+1],&q)!=TCL_OK)return TCL_ERROR;
    a->f[axis]-=2*coefficient*q*dipole;
  }
  for(int i=0;i<nm;++i) {
    auto *a=get(mobile[i]);if(!a)return TCL_ERROR;
    double z=a->x[axis],d=z<low?z-low:z>high?z-high:0;
    a->f[axis]-=wall*d;energy+=.5*wall*d*d;
  }
  for(int i=0;i<ns;i+=2) {
    auto *a=get(sites[i]);Tcl_Obj **v;int n;double k;
    if(!a || Tcl_ListObjGetElements(ip,sites[i+1],&n,&v)!=TCL_OK || n!=4 || Tcl_GetDoubleFromObj(ip,v[3],&k)!=TCL_OK)return TCL_ERROR;
    for(int j=0;j<3;++j) {
      double x;if(Tcl_GetDoubleFromObj(ip,v[j],&x)!=TCL_OK)return TCL_ERROR;
      double d=a->x[j]-x;a->f[j]-=k*d;energy+=.5*k*d*d;
    }
  }
  for(size_t i=1;i<atoms.size();++i) if(atoms[i].touched) {
    const auto &f=atoms[i].f;
    self->modifyForcedAtoms().add(static_cast<int>(i)-1);
    self->modifyAppliedForces().add(Vector(f[0],f[1],f[2]));
  }
  self->addReductionEnergy(REDUCTION_MISC_ENERGY,energy);
  if(audit) {
    Tcl_Obj *result=Tcl_NewListObj(0,nullptr);
    Tcl_ListObjAppendElement(ip,result,Tcl_NewDoubleObj(energy));
    for(size_t i=1;i<atoms.size();++i) if(atoms[i].touched) {
      Tcl_Obj *values[4]={Tcl_NewIntObj(static_cast<int>(i)),Tcl_NewDoubleObj(atoms[i].f[0]),Tcl_NewDoubleObj(atoms[i].f[1]),Tcl_NewDoubleObj(atoms[i].f[2])};
      Tcl_ListObjAppendElement(ip,result,Tcl_NewListObj(4,values));
    }
    Tcl_SetObjResult(ip,result);
  }
  return TCL_OK;
}
