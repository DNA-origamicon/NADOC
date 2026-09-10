#include "chudoba_math.h"
#include <chrono>
#include <cstdio>
int main(){
 double sum=0,du; volatile double temperature=371.;
 auto start=std::chrono::steady_clock::now();
 for(int i=0;i<10000000;i++){
  double r=.35+(i%1000)*.0005;
  sum+=chudoba::pair(r,double(temperature),du)+du;
 }
 printf("seconds %.8f checksum %.16g\n",std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count(),sum);
}
