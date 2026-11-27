export const volumeVertex=`
attribute float corner;
attribute vec3 p0,p1,p2,p3;
attribute vec4 b0,b1,b2,values;
flat varying vec4 plane0,plane1,plane2,intensities;
void main(){
 plane0=b0;plane1=b1;plane2=b2;intensities=values;
 vec3 p=corner<.5?p0:corner<1.5?p1:corner<2.5?p2:p3;
 gl_Position=projectionMatrix*viewMatrix*vec4(p,1.);
}`
export const volumeFragment=`
uniform sampler2D sceneDepth,palette;
uniform mat4 inverseProjection,cameraWorld;
uniform vec2 viewportSize;
uniform float cutoff,colorLow,colorHigh,weight;
flat varying vec4 plane0,plane1,plane2,intensities;
vec3 world(vec2 uv,float z){vec4 p=inverseProjection*vec4(uv*2.-1.,z,1.);return (cameraWorld*vec4(p.xyz/p.w,1.)).xyz;}
void main(){
 vec2 uv=gl_FragCoord.xy/viewportSize;
 vec3 origin=world(uv,-1.),direction=normalize(world(uv,1.)-origin);
 float depth=texture2D(sceneDepth,uv).x;
 float lo=0.,hi=length(world(uv,depth*2.-1.)-origin);
 vec4 q=vec4(dot(plane0,vec4(origin,1.)),dot(plane1,vec4(origin,1.)),dot(plane2,vec4(origin,1.)),0.);
 vec4 d=vec4(dot(plane0.xyz,direction),dot(plane1.xyz,direction),dot(plane2.xyz,direction),0.);
 q.w=1.-q.x-q.y-q.z;d.w=-d.x-d.y-d.z;
 for(int i=0;i<4;i++){
  if(abs(d[i])<1.e-9){if(q[i]<-1.e-6)discard;}
  else if(d[i]>0.)lo=max(lo,-q[i]/d[i]);else hi=min(hi,-q[i]/d[i]);
 }
 float base=dot(q,intensities),slope=dot(d,intensities),threshold=max(1.,cutoff);
 if(abs(slope)<1.e-9){if(base<threshold)discard;}
 else if(slope>0.)lo=max(lo,(threshold-base)/slope);else hi=min(hi,(threshold-base)/slope);
 if(!(hi>lo))discard;
 // Eight-point Gauss-Legendre integration of the transfer function on the
 // exact clipped interval. No fixed spatial step can skip a refined cell.
 float nodes[8];nodes[0]=-.960289856;nodes[1]=-.796666477;nodes[2]=-.525532410;nodes[3]=-.183434642;
 nodes[4]=.183434642;nodes[5]=.525532410;nodes[6]=.796666477;nodes[7]=.960289856;
 float weights[8];weights[0]=.101228536;weights[1]=.222381034;weights[2]=.313706646;weights[3]=.362683783;
 weights[4]=.362683783;weights[5]=.313706646;weights[6]=.222381034;weights[7]=.101228536;
 vec3 emission=vec3(0.);
 // Linear interpolation inside a tetrahedron cannot exceed its sample range.
 // Enforce that invariant despite cancellation in GPU ray/plane arithmetic.
 float lower=max(1.,min(min(intensities.x,intensities.y),min(intensities.z,intensities.w)));
 float upper=max(lower,max(max(intensities.x,intensities.y),max(intensities.z,intensities.w)));
 for(int i=0;i<8;i++){
  float value=clamp(base+slope*((lo+hi)*.5+(hi-lo)*.5*nodes[i]),lower,upper);
  float f=clamp(log(value/colorLow)/log(colorHigh/colorLow),0.,1.);
  vec3 color=texture2D(palette,vec2((f*255.+.5)/256.,.5)).rgb;
  // Illustrative emission: 100x contributes 2 radiance units per 10 nm.
  emission+=weights[i]*color*(value-1.)/99.;
 }
 emission*=.1*(hi-lo)*weight;
 gl_FragColor=vec4(emission,max(emission.r,max(emission.g,emission.b)));
}`
