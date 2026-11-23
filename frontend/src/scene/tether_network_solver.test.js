import { describe, it, expect } from 'vitest'
import { createTetherNetworkSolver } from './tether_network_solver.js'
const model = () => ({ driver:'arm',fixed:'root',
  bodies:{ root:{center:[0,0,0],size:100,radius:2}, arm:{center:[6,0,0],size:80,radius:2},
    link:{center:[3,0,0],size:2,radius:1} },
  rods:[], edges:[{a:'root',b:'link',pa:[0,0,0],pb:[2,0,0],contour:2},
    {a:'link',b:'arm',pa:[4,0,0],pb:[6,0,0],contour:2}] })
describe('compliant tether network', () => {
  it('lets an intermediate body yield while keeping the anchor exactly fixed', () => {
    const solver=createTetherNetworkSolver(model())
    const result=solver.solve({pos:[6,1,0],quat:[0,0,0,1]})
    expect(result.poses.root).toEqual({pos:[0,0,0],quat:[0,0,0,1]})
    expect(result.poses.arm.pos[1]).toBeGreaterThan(.5)
    expect(result.poses.link.pos[1]).toBeGreaterThan(.01)
    expect(result.tether).toBeLessThanOrEqual(.001)
  })
  it('reverses a compliant motion without retaining a one-way contact barrier', () => {
    const solver=createTetherNetworkSolver(model())
    solver.solve({pos:[6,1,0],quat:[0,0,0,1]})
    const result=solver.solve({pos:[6,-1,0],quat:[0,0,0,1]})
    expect(result.poses.arm.pos[1]).toBeLessThan(-.5)
    expect(result.poses.link.pos[1]).toBeLessThan(0)
    expect(result.tether).toBeLessThanOrEqual(.001)
  })
  it('does not allow the pinned largest owner to be driven', () => {
    const m=model();m.driver='root'
    expect(createTetherNetworkSolver(m).solve({pos:[1,2,3],quat:[0,0,0,1]}).poses.root.pos).toEqual([0,0,0])
  })
  it('lets a smaller body yield at contact against an independent fixed obstacle', () => {
    const m=model()
    m.edges=[]
    m.rods=[{owner:'arm',p:[6,0,0],q:[6,0,2]}, {owner:'link',p:[3,0,0],q:[3,0,2]},
      {owner:'obstacle',p:[0,0,0],q:[0,0,2]}]
    const result=createTetherNetworkSolver(m).solve({pos:[4.2,0,0],quat:[0,0,0,1]})
    expect(result.poses.link.pos[0]).toBeLessThan(2.3)
    expect(result.poses.arm.pos[0]).toBeLessThan(4.3)
    expect(result.penetration).toBeLessThanOrEqual(.001)
  })
})
it('samples a large requested move and stops before a fixed barrier', () => {
  const m=model(); m.edges=[]
  m.rods=[{owner:'arm',p:[6,0,0],q:[6,0,2]}, {owner:'obstacle',p:[9,0,0],q:[9,0,2]}]
  const solver=createTetherNetworkSolver(m)
  expect(solver.solve({pos:[12,0,0],quat:[0,0,0,1]}).poses.arm.pos[0]).toBeLessThanOrEqual(7.001)
  expect(solver.solve({pos:[5,0,0],quat:[0,0,0,1]}).poses.arm.pos[0]).toBeLessThan(5.01)
  expect(solver.solve({pos:[12,0,0],quat:[0,0,0,1]},false).poses.arm.pos[0]).toBe(12)
})
it('continues a time-sliced projection without publishing invalid poses or blocking reversal',()=>{
  let clock=0
  const solver=createTetherNetworkSolver(model(),{now:()=>clock++,budgetMs:4})
  const target={pos:[6,1,0],quat:[0,0,0,1]}
  const first=solver.solve(target)
  expect(first.poses.arm.pos).toEqual([6,0,0])
  let result=first
  for(let i=0;i<80;i++){
    result=solver.solve(target)
    expect(result.tether).toBeLessThanOrEqual(.001)
    expect(result.penetration).toBeLessThanOrEqual(.001)
  }
  expect(result.poses.arm.pos[1]).toBeGreaterThan(.5)
  for(let i=0;i<120;i++)result=solver.solve({...target,pos:[6,-1,0]})
  expect(result.poses.arm.pos[1]).toBeLessThan(-.5)
})
