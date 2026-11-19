import {it,expect} from 'vitest'
import {createTetherContactIndex} from './tether_contact_index.js'
it('matches exhaustive bounds queries after large body motion and reversal',()=>{
  const geometry=Array.from({length:80},()=>({lo:[0,0,0],hi:[0,0,0]})), pairs=[]
  for(let i=0;i<80;i++)for(let j=0;j<i;j++)if(i%3!==j%3)pairs.push([i,j])
  const query=createTetherContactIndex(geometry,pairs,2.334)
  for(let frame=0;frame<12;frame++){
    geometry.forEach((b,i)=>{for(let c=0;c<3;c++){
      b.lo[c]=Math.sin(i*17+c*7+frame)*20;b.hi[c]=b.lo[c]+(i%9===0?30:2)
    }})
    const expected=pairs.flatMap(([i,j],k)=>{
      const a=geometry[i],b=geometry[j]
      const distance=[0,1,2].reduce((sum,c)=>sum+Math.max(0,a.lo[c]-b.hi[c],b.lo[c]-a.hi[c])**2,0)
      return distance<=2.334**2?[k]:[]
    })
    expect(query()).toEqual(expected)
  }
})
