import { afterEach, beforeEach, test } from 'node:test'
import assert from 'node:assert/strict'
import cytoscape from 'cytoscape'
import { createConstellationMotion } from '../src/components/knowledge/constellationMotion.ts'

let frames, now, cy, motion, reduced, events
const original = { raf: globalThis.requestAnimationFrame, cancel: globalThis.cancelAnimationFrame, document: globalThis.document }
beforeEach(() => {
  frames = new Map(); now = 0; reduced = false; events = []
  let next = 0
  globalThis.requestAnimationFrame = callback => { frames.set(++next, callback); return next }
  globalThis.cancelAnimationFrame = id => frames.delete(id)
  globalThis.document = { hidden: false }
  cy = cytoscape({ headless: true, layout: { name: 'preset' }, elements: [
    ...['a','b','c','other'].map((id,i) => ({ data: { id }, position: { x: i*140, y: 0 } })),
    { data: { id:'ab', source:'a', target:'b' } }, { data: { id:'bc', source:'b', target:'c' } },
  ] })
  motion = createConstellationMotion(cy, { reduced: () => reduced, onDrag: active => events.push(active) })
})
afterEach(() => {
  motion.destroy(); cy.destroy()
  globalThis.requestAnimationFrame = original.raf
  globalThis.cancelAnimationFrame = original.cancel
  if (original.document === undefined) delete globalThis.document
  else globalThis.document = original.document
})
function advance(count = 1) {
  for (let i=0; i<count; i++) {
    now += 16.667
    const pending = [...frames.values()]; frames.clear()
    pending.forEach(callback => callback(now))
  }
}
function drag(x = 220) { cy.$id('a').emit('grab'); cy.$id('a').position({ x, y: 80 }); advance(30) }

test('drag pulls connected stars without moving the grabbed star or another constellation', () => {
  const other = { ...cy.$id('other').position() }
  drag()
  assert.ok(Math.abs(cy.$id('b').position('y')) > 5)
  assert.deepEqual(cy.$id('a').position(), { x:220, y:80 })
  assert.deepEqual(cy.$id('other').position(), other)
  assert.equal(motion.dragging, true)
  assert.equal(cy.$id('ab').hasClass('tethered'), true)
})
test('release has a damped settling phase then stops requesting animation frames', () => {
  drag()
  cy.$id('a').emit('free')
  assert.equal(motion.dragging, false)
  assert.equal(motion.active, true)
  const before = { ...cy.$id('b').position() }
  advance(10)
  assert.notDeepEqual(cy.$id('b').position(), before)
  advance(500)
  assert.equal(motion.active, false)
  assert.equal(frames.size, 0)
  assert.deepEqual(cy.$id('a').position(), { x:220, y:80 })
  assert.equal(cy.$id('ab').hasClass('tethered'), false)
})
test('reduced motion keeps native dragging but disables neighbour simulation', () => {
  reduced = true
  const before = { ...cy.$id('b').position() }
  drag()
  assert.deepEqual(cy.$id('b').position(), before)
  assert.equal(frames.size, 0)
  cy.$id('a').emit('free')
  assert.equal(motion.active, false)
})
test('switching to reduced motion or hiding the page cancels an active simulation', () => {
  drag(); reduced = true; advance()
  assert.equal(frames.size, 0)
  reduced = false; drag(); document.hidden = true; advance()
  assert.equal(motion.active, false)
  assert.equal(frames.size, 0)
})
test('extreme drag and overlapping stars remain finite and settle', () => {
  cy.$id('b').position(cy.$id('c').position())
  drag(10000); cy.$id('a').emit('free'); advance(500)
  cy.nodes().forEach(node => {
    assert.ok(Number.isFinite(node.position('x')))
    assert.ok(Number.isFinite(node.position('y')))
  })
  assert.equal(frames.size, 0)
})
test('a new drag replaces the old animation loop and unmount removes listeners', () => {
  drag(); cy.$id('b').emit('grab'); advance()
  assert.equal(frames.size, 1)
  motion.destroy()
  assert.equal(frames.size, 0)
  const count = events.length
  cy.$id('c').emit('grab'); advance()
  assert.equal(events.length, count)
})
