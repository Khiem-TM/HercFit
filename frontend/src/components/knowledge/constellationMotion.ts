import type { Core, EventObject, NodeSingular, Position } from 'cytoscape'

type Body = { node: NodeSingular; home: Position; velocity: Position; force: Position }
type Spring = { a: Body; b: Body; length: number }
export interface MotionOptions {
  reduced: () => boolean
  onDrag: (dragging: boolean, node?: NodeSingular) => void
  onFrame?: (node: NodeSingular) => void
}

/** A short-lived spring simulation, active only during a drag and its settling.
 * Cytoscape owns the grabbed node. Only its connected neighbours are simulated.
 * Coordinates are presentation state; graph records are never changed.
 */
export function createConstellationMotion(cy: Core, options: MotionOptions) {
  let bodies: Body[] = []
  let springs: Spring[] = []
  let held: NodeSingular | undefined
  let anchor: NodeSingular | undefined
  let frame = 0
  let previous = 0
  let quietFrames = 0
  let elapsed = 0
  let disposed = false

  function stop() {
    cancelAnimationFrame(frame)
    frame = 0
    bodies = []
    springs = []
    held = undefined
    anchor = undefined
    cy.elements().removeClass('tethered held')
    options.onDrag(false)
  }

  function tick(time: number) {
    if (disposed || options.reduced() || document.hidden || !anchor || anchor.removed()) {
      stop()
      return
    }
    const dt = previous ? Math.min((time - previous) / 16.667, 1.5) : 1
    previous = time
    elapsed += dt
    for (const body of bodies) {
      const position = body.node.position()
      body.force = { x: (body.home.x - position.x) * .014, y: (body.home.y - position.y) * .014 }
    }
    for (const { a, b, length } of springs) {
      const pa = a.node.position(), pb = b.node.position()
      const dx = pb.x - pa.x, dy = pb.y - pa.y
      const distance = Math.max(1, Math.hypot(dx, dy))
      const force = Math.max(-12, Math.min(12, (distance - length) * .027))
      a.force.x += dx / distance * force
      a.force.y += dy / distance * force
      b.force.x -= dx / distance * force
      b.force.y -= dy / distance * force
    }
    // Keep adjacent stars legible when a constellation folds over itself.
    for (let i = 0; i < bodies.length; i++) {
      for (let j = i + 1; j < bodies.length; j++) {
        const a = bodies[i], b = bodies[j]
        const pa = a.node.position(), pb = b.node.position()
        const dx = pb.x - pa.x, dy = pb.y - pa.y
        const distance = Math.hypot(dx, dy)
        if (distance >= 62 || distance < .01) continue
        const force = (62 - distance) * .035
        a.force.x -= dx / distance * force
        a.force.y -= dy / distance * force
        b.force.x += dx / distance * force
        b.force.y += dy / distance * force
      }
    }
    let speed = 0
    cy.batch(() => {
      for (const body of bodies) {
        if (body.node === anchor || body.node.grabbed() || body.node.locked() || body.node.removed()) continue
        body.velocity.x = (body.velocity.x + body.force.x * dt) * Math.pow(.79, dt)
        body.velocity.y = (body.velocity.y + body.force.y * dt) * Math.pow(.79, dt)
        const magnitude = Math.hypot(body.velocity.x, body.velocity.y)
        if (magnitude > 11) {
          body.velocity.x *= 11 / magnitude
          body.velocity.y *= 11 / magnitude
        }
        const position = body.node.position()
        body.node.position({ x: position.x + body.velocity.x * dt, y: position.y + body.velocity.y * dt })
        speed = Math.max(speed, Math.hypot(body.velocity.x, body.velocity.y))
      }
    })
    options.onFrame?.(anchor)
    quietFrames = !held && speed < .045 ? quietFrames + 1 : 0
    if (!held && (quietFrames >= 12 || elapsed > 420)) {
      stop()
      return
    }
    frame = requestAnimationFrame(tick)
  }

  function grab(event: EventObject) {
    stop()
    const node = event.target as NodeSingular
    held = anchor = node
    options.onDrag(true, node)
    node.addClass('held')
    node.closedNeighborhood().addClass('tethered')
    if (options.reduced()) return
    const component = node.component()
    bodies = component.nodes().map(n => ({ node: n, home: { ...n.position() }, velocity: { x: 0, y: 0 }, force: { x: 0, y: 0 } }))
    const byId = new Map(bodies.map(b => [b.node.id(), b]))
    springs = component.edges().map(e => {
      const a = byId.get(e.source().id())!, b = byId.get(e.target().id())!
      return { a, b, length: Math.max(65, Math.hypot(a.home.x - b.home.x, a.home.y - b.home.y)) }
    })
    previous = quietFrames = elapsed = 0
    frame = requestAnimationFrame(tick)
  }

  function free() {
    if (!held) return
    held.removeClass('held')
    held = undefined
    options.onDrag(false, anchor)
    if (options.reduced()) stop()
  }

  cy.on('grab', 'node', grab)
  cy.on('free', 'node', free)
  return {
    stop,
    get active() { return frame !== 0 || held !== undefined },
    get dragging() { return held !== undefined },
    destroy() {
      disposed = true
      stop()
      cy.off('grab', 'node', grab)
      cy.off('free', 'node', free)
    },
  }
}
