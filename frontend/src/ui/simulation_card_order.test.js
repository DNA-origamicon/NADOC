import { beforeEach, describe, expect, it } from 'vitest'
import { standardizeSimulationCardOrder } from './simulation_card_order.js'

describe('standard simulation card order', () => {
  beforeEach(() => { document.body.innerHTML = '' })
  const card = title => {
    const node = document.createElement('div')
    node.className = 'ox-card'
    node.innerHTML = `<div class="ox-card__header"><span class="ox-card__title">${title}</span></div>`
    return node
  }

  it('orders cards without moving intervening non-card panel state', () => {
    const body = document.createElement('div')
    const status = document.createElement('div')
    body.append(card('Graphs and Metrics'), status, card('Electric field'), card('Clusters'), card('Anchors'))
    document.body.append(body)
    expect(standardizeSimulationCardOrder(body)).toEqual(['Clusters', 'Anchors', 'Electric field', 'Graphs and Metrics'])
    expect(body.children[1]).toBe(status)
  })

  it('keeps unknown cards stable at the end', () => {
    const body = document.createElement('div')
    body.append(card('Custom B'), card('Visualizations'), card('Custom A'))
    expect(standardizeSimulationCardOrder(body)).toEqual(['Visualizations', 'Custom B', 'Custom A'])
  })
})
