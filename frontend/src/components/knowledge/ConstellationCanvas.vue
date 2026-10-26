<script setup lang="ts">
import { onMounted, onUnmounted, shallowRef, useTemplateRef, watch } from 'vue'
import cytoscape, { type Collection, type Core, type NodeSingular, type StylesheetCSS } from 'cytoscape'
import type { KnowledgeNode } from '@/types/knowledge'
import { hubColor, ROOT_COLOR } from '@/types/knowledge'
import { createConstellationMotion } from './constellationMotion'
import { ancestors, radialLayout, visibleEdges, type Point, type TreeIndex } from './knowledgeTree'

const props = defineProps<{ index: TreeIndex; visible: string[]; expanded: ReadonlySet<string>; selectedId?: string }>()
const emit = defineEmits<{ activate: [id: string]; clear: [] }>()
const host = useTemplateRef<HTMLDivElement>('host')
const sky = useTemplateRef<HTMLDivElement>('sky')
const aura = useTemplateRef<HTMLDivElement>('aura')
const dragging = shallowRef(false)
const hovering = shallowRef(false)
const hinted = shallowRef(true)
const reduced = shallowRef(false)
let cy: Core | undefined
let motion: ReturnType<typeof createConstellationMotion> | undefined
let resize: ResizeObserver | undefined
let preference: MediaQueryList | undefined
let focused: NodeSingular | undefined
let queued = false
let disposed = false
let painted = false
const ORBITS = [165, 300, 425, 540]
const SIZE: Record<string, number> = { User: 74, Hub: 52, Group: 36, Goal: 32, Exercise: 30, Food: 28, Intent: 30 }
const glyphs = new Map<string, string>()

const stars = Array.from({ length: 110 }, (_, i) => ({
  left: `${(i * 73.137) % 100}%`, top: `${(i * 47.391) % 100}%`,
  '--brightness': .14 + (i % 6) * .07, '--twinkle': `${4 + i % 7}s`,
  animationDelay: `${-(i % 13)}s`, width: `${i % 9 === 0 ? 2 : 1}px`,
}))

/** Hubs are suns, groups are rings, records are stars: shape tells depth at a glance. */
function glyph(kind: string, color: string) {
  const key = `${kind}:${color}`
  if (glyphs.has(key)) return glyphs.get(key)!
  const star = `<path d="M40 14L42 37L64 40L42 43L40 66L38 43L16 40L38 37Z" fill="${color}" opacity=".9"/><circle cx="40" cy="40" r="3" fill="#fffaf0"/>`
  const halo = `<defs><radialGradient id="g"><stop stop-color="${color}" stop-opacity=".55"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></radialGradient></defs><circle cx="40" cy="40" r="38" fill="url(#g)"/>`
  const body = kind === 'Hub'
    ? `${halo}<circle cx="40" cy="40" r="17" fill="${color}" opacity=".9"/><circle cx="40" cy="40" r="24" fill="none" stroke="${color}" stroke-opacity=".45"/><circle cx="40" cy="40" r="5" fill="#fffaf0" opacity=".9"/>`
    : kind === 'User'
      ? `${halo}<circle cx="40" cy="40" r="30" fill="none" stroke="${color}" stroke-opacity=".35"/>${star}`
      : kind === 'Group'
        ? `${halo}<circle cx="40" cy="40" r="15" fill="#101216" stroke="${color}" stroke-width="2.5"/><circle cx="40" cy="40" r="5" fill="${color}"/>`
        : `${halo}${star}`
  const url = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 80 80">${body}</svg>`)
  glyphs.set(key, url)
  return url
}

function display(node: KnowledgeNode) {
  if (node.kind === 'Hub') return node.summary ? `${node.label}\n${node.summary}` : node.label
  if (node.kind === 'Group') return `${node.label} · ${node.count ?? node.children}`
  if (node.kind === 'Food' || node.kind === 'Exercise' || node.kind === 'Intent') return node.summary ? `${node.label}\n${node.summary}` : node.label
  return node.label
}

function nodeData(node: KnowledgeNode) {
  const color = node.kind === 'User' ? ROOT_COLOR : hubColor(node.hub)
  const size = SIZE[node.kind] ?? (node.depth >= 4 ? 18 : 24)
  return { id: node.id, kind: node.kind, display: display(node), color, size, glyph: glyph(node.kind, color),
           font: node.kind === 'User' ? 15 : node.kind === 'Hub' ? 12 : node.depth >= 4 ? 9 : 10.5 }
}

function animateTo(node: NodeSingular, position: Point, opacity = 1, done?: () => void) {
  node.stop()
  // A visible star drops its inline opacity so class styles (muted, trail) apply again.
  const settle = () => { if (opacity === 1) node.removeStyle('opacity'); done?.() }
  if (reduced.value) {
    node.position(position).style('opacity', opacity)
    settle()
    return
  }
  node.animate({ position, style: { opacity } }, { duration: 560, easing: 'ease-in-out-cubic', complete: settle })
}

function render() {
  if (!cy || disposed) return
  if (motion?.dragging) { queued = true; return }
  const visible = new Set(props.visible)
  const targets = radialLayout(props.index, props.visible)
  const edges = visibleEdges(props.index, visible).map(edge => ({ ...edge, id: `${edge.kind}:${edge.source}>${edge.target}` }))
  const wanted = new Set(edges.map(edge => edge.id))
  const added: NodeSingular[] = []
  cy.batch(() => {
    cy!.edges().filter(edge => !wanted.has(edge.id())).remove()
    // Folding branches glide back into their parent before disappearing.
    cy!.nodes('.knowledge').forEach(node => {
      if (visible.has(node.id()) || node.hasClass('leaving')) return
      const parent = props.index.byId.get(node.id())?.parent
      const home = (parent && targets.get(parent)) || { x: 0, y: 0 }
      node.addClass('leaving').ungrabify()
      animateTo(node, home, 0, () => node.remove())
    })
    for (const id of props.visible) {
      const record = props.index.byId.get(id)
      if (!record) continue
      const target = targets.get(id) ?? { x: 0, y: 0 }
      const existing = cy!.getElementById(id)
      if (existing.nonempty()) {
        existing.removeClass('leaving').grabify().data(nodeData(record))
        animateTo(existing as NodeSingular, target)
        continue
      }
      const parent = record.parent ? cy!.getElementById(record.parent) as NodeSingular : undefined
      // New stars bloom out of their parent; the very first sky is drawn in place so it can be framed.
      const origin = painted && parent?.nonempty() ? { ...parent.position() } : target
      const node = cy!.add({ group: 'nodes', data: nodeData(record), position: origin, classes: 'knowledge' })
      node.style('opacity', painted ? 0 : 1)
      added.push(node as NodeSingular)
      animateTo(node as NodeSingular, target)
    }
    for (const edge of edges) {
      if (cy!.getElementById(edge.id).nonempty() || cy!.getElementById(edge.source).empty() || cy!.getElementById(edge.target).empty()) continue
      const color = edge.kind === 'link' ? '#d4b77d' : hubColor(props.index.byId.get(edge.target)?.hub)
      cy!.add({ group: 'edges', data: { id: edge.id, source: edge.source, target: edge.target, kind: edge.kind, color } })
    }
    const depth = Math.max(0, ...props.visible.map(id => props.index.byId.get(id)?.depth ?? 0))
    cy!.nodes('.orbit').forEach((orbit, i) => { orbit.style('opacity', i < depth ? .55 : 0) })
  })
  for (const id of props.visible) {
    cy.getElementById(id).toggleClass('expandable', (props.index.byId.get(id)?.children ?? 0) > 0)
      .toggleClass('open', props.expanded.has(id))
  }
  highlight()
  if (!painted) {
    painted = true
    requestAnimationFrame(() => fit(false))
  } else if (added.length) {
    hinted.value = false
    // Keep a branch that just opened, and the star that opened it, on screen.
    const parentId = props.index.byId.get(added[0].id())?.parent
    const parent = parentId ? cy.getElementById(parentId) : cy.collection()
    reveal(added.reduce<Collection>((all, node) => all.union(node), parent), targets)
  }
}

function reveal(collection: Collection, targets: Map<string, Point>) {
  if (!cy || collection.empty()) return
  const points = collection.nodes().map(node => targets.get(node.id()) ?? node.position())
  const box = { x1: Math.min(...points.map(p => p.x)) - 70, x2: Math.max(...points.map(p => p.x)) + 70,
                y1: Math.min(...points.map(p => p.y)) - 70, y2: Math.max(...points.map(p => p.y)) + 70 }
  const view = cy.extent()
  if (box.x1 >= view.x1 && box.x2 <= view.x2 && box.y1 >= view.y1 && box.y2 <= view.y2) return
  const zoom = Math.min(cy.zoom(), cy.width() / (box.x2 - box.x1), cy.height() / (box.y2 - box.y1))
  const level = Math.max(cy.minZoom(), Math.min(1, zoom))
  const center = { x: (box.x1 + box.x2) / 2, y: (box.y1 + box.y2) / 2 }
  const pan = { x: cy.width() / 2 - center.x * level, y: cy.height() / 2 - center.y * level }
  if (reduced.value) cy.viewport({ zoom: level, pan })
  else cy.stop().animate({ zoom: level, pan }, { duration: 650, easing: 'ease-in-out-cubic' })
}

function highlight() {
  if (!cy) return
  cy.batch(() => {
    cy!.elements().removeClass('chosen trail muted')
    if (!props.selectedId) return
    const node = cy!.getElementById(props.selectedId)
    if (node.empty()) return
    const path = [...ancestors(props.index, props.selectedId), props.selectedId]
    const lit = path.reduce<Collection>((all, id) => all.union(cy!.getElementById(id)), node.closedNeighborhood())
    lit.merge(lit.nodes().edgesWith(lit.nodes()))
    cy!.elements('.knowledge, edge').not(lit).addClass('muted')
    lit.addClass('trail')
    node.addClass('chosen')
  })
}

function follow(node: NodeSingular) {
  if (!aura.value || node.removed()) return
  const position = node.renderedPosition()
  aura.value.style.setProperty('--halo-x', `${position.x}px`)
  aura.value.style.setProperty('--halo-y', `${position.y}px`)
  aura.value.style.setProperty('--halo-color', node.data('color'))
}

function parallax(event: PointerEvent) {
  if (reduced.value || !sky.value || event.pointerType !== 'mouse') return
  const rect = sky.value.getBoundingClientRect()
  sky.value.style.setProperty('--parallax-x', `${((event.clientX - rect.left) / rect.width - .5) * 12}px`)
  sky.value.style.setProperty('--parallax-y', `${((event.clientY - rect.top) / rect.height - .5) * 10}px`)
}

function resetParallax() {
  sky.value?.style.setProperty('--parallax-x', '0px')
  sky.value?.style.setProperty('--parallax-y', '0px')
}

function onPreference() {
  reduced.value = preference?.matches ?? false
  if (reduced.value) { motion?.stop(); cy?.stop(); cy?.elements().stop(); resetParallax() }
}

function onVisibility() { if (document.hidden) { motion?.stop(); hovering.value = false } }

function fit(animate = true) {
  if (!cy || motion?.dragging) return
  const nodes = cy.nodes('.knowledge').not('.leaving')
  if (nodes.empty()) return
  if (reduced.value || !animate) cy.fit(nodes, 56)
  else cy.stop().animate({ fit: { eles: nodes, padding: 56 } }, { duration: 600, easing: 'ease-out-cubic' })
}

function zoom(factor: number) {
  if (!cy || motion?.dragging) return
  const level = Math.max(cy.minZoom(), Math.min(cy.maxZoom(), cy.zoom() * factor))
  const center = { x: cy.width() / 2, y: cy.height() / 2 }
  const pan = { x: center.x - (center.x - cy.pan().x) * level / cy.zoom(), y: center.y - (center.y - cy.pan().y) * level / cy.zoom() }
  if (reduced.value) cy.viewport({ zoom: level, pan })
  else cy.stop().animate({ zoom: level, pan }, { duration: 300, easing: 'ease-out-cubic' })
}

/** Centre a node, e.g. after choosing it from the timeline or the inspector. */
function focus(id: string) {
  const node = cy?.getElementById(id)
  if (!cy || !node || node.empty()) return
  const target = radialLayout(props.index, props.visible).get(id) ?? node.position()
  const level = Math.min(Math.max(cy.zoom(), .7), 1.05)
  const pan = { x: cy.width() / 2 - target.x * level, y: cy.height() / 2 - target.y * level }
  if (reduced.value) cy.viewport({ zoom: level, pan })
  else cy.stop().animate({ zoom: level, pan }, { duration: 650, easing: 'ease-in-out-cubic' })
}

const STYLE = [
  { selector: 'node.knowledge', style: {
    width: 'data(size)', height: 'data(size)', 'background-opacity': 0, 'background-image': 'data(glyph)', 'background-fit': 'contain',
    'background-clip': 'none', label: 'data(display)', color: '#c9c5bb', 'font-size': 'data(font)', 'font-family': 'Geist, sans-serif',
    'text-valign': 'bottom', 'text-margin-y': 4, 'text-wrap': 'wrap', 'text-max-width': '132px', 'line-height': 1.35,
    'text-outline-width': 3, 'text-outline-color': '#101216', 'min-zoomed-font-size': 7, 'overlay-opacity': 0,
    'underlay-color': 'data(color)', 'underlay-opacity': 0, 'underlay-padding': 7, 'underlay-shape': 'ellipse',
    'border-width': 0, 'border-color': 'data(color)', 'z-index-compare': 'manual', 'z-index': 10,
    'transition-property': 'underlay-opacity, border-width, border-opacity', 'transition-duration': 220 } },
  { selector: 'node[kind="User"]', style: { color: '#fff1ce', 'font-family': 'Playfair Display, serif', 'text-margin-y': 6 } },
  { selector: 'node[kind="Hub"]', style: { color: '#ece4d2', 'text-margin-y': 6, 'font-weight': 500 } },
  { selector: 'node.expandable', style: { 'border-width': 1.2, 'border-style': 'dashed', 'border-opacity': .6 } },
  { selector: 'node.open', style: { 'border-width': 1.6, 'border-style': 'solid', 'border-opacity': .9, 'underlay-opacity': .07 } },
  { selector: 'node.orbit', style: {
    width: 'data(size)', height: 'data(size)', 'background-opacity': 0, 'border-width': 1, 'border-color': '#d4b77d',
    'border-opacity': .09, label: '', events: 'no', 'z-index-compare': 'manual', 'z-index': 0, 'underlay-opacity': 0,
    'transition-property': 'opacity', 'transition-duration': 500 } },
  { selector: 'edge', style: {
    width: 1, 'line-color': 'data(color)', opacity: .34, 'curve-style': 'bezier', 'target-arrow-shape': 'none',
    'z-index-compare': 'manual', 'z-index': 5, 'transition-property': 'opacity, width', 'transition-duration': 260 } },
  { selector: 'edge[kind="link"]', style: {
    'line-style': 'dashed', 'line-dash-pattern': [4, 5], width: .9, opacity: .45,
    'curve-style': 'unbundled-bezier', 'control-point-distances': 36, 'control-point-weights': .5 } },
  { selector: '.muted', style: { opacity: .16 } },
  { selector: 'node.trail', style: { 'underlay-opacity': .06 } },
  { selector: 'edge.trail', style: { opacity: .9, width: 1.6 } },
  { selector: 'node.chosen', style: { 'underlay-opacity': .2, color: '#fff3d5', 'z-index': 30 } },
  { selector: 'node.hovered, node.held', style: { 'underlay-opacity': .15, color: '#fff3d5', 'z-index': 20 } },
  { selector: 'edge.hovered, edge.tethered', style: { opacity: .9, width: 1.6 } },
] as unknown as StylesheetCSS[]

onMounted(() => {
  preference = window.matchMedia('(prefers-reduced-motion: reduce)')
  reduced.value = preference.matches
  preference.addEventListener('change', onPreference)
  cy = cytoscape({ container: host.value!, minZoom: .2, maxZoom: 2.4, wheelSensitivity: .15, boxSelectionEnabled: false,
                   selectionType: 'single', autoungrabify: false, style: STYLE })
  cy.add(ORBITS.map((radius, i) => ({ group: 'nodes' as const, data: { id: `orbit:${i}`, size: radius * 2 },
                                       position: { x: 0, y: 0 }, classes: 'orbit', grabbable: false, selectable: false })))
  cy.nodes('.orbit').style('opacity', 0)
  motion = createConstellationMotion(cy, {
    reduced: () => reduced.value,
    onDrag(active, node) {
      dragging.value = active
      if (node) { focused = node; follow(node) }
      if (!active && queued) { queued = false; queueMicrotask(render) }
    },
    onFrame: follow,
  })
  cy.on('mouseover', 'node.knowledge', event => {
    focused = event.target
    hovering.value = true
    focused!.addClass('hovered').connectedEdges().addClass('hovered')
    follow(focused!)
  })
  cy.on('mouseout', 'node.knowledge', event => {
    event.target.removeClass('hovered').connectedEdges().removeClass('hovered')
    hovering.value = false
  })
  cy.on('pan zoom', () => { if (focused) follow(focused) })
  cy.on('tap', 'node.knowledge', event => {
    hinted.value = false
    if (!event.target.hasClass('leaving')) emit('activate', event.target.id())
  })
  setTimeout(() => { hinted.value = false }, 7000)
  cy.on('tap', event => { if (event.target === cy) emit('clear') })
  // Resizing the panel or the details keeps the middle of the sky in the middle.
  let frame = { width: 0, height: 0 }
  resize = new ResizeObserver(([entry]) => {
    if (!cy || !entry) return
    const { width, height } = entry.contentRect
    if (frame.width && frame.height && !motion?.dragging) cy.panBy({ x: (width - frame.width) / 2, y: (height - frame.height) / 2 })
    frame = { width, height }
    cy.resize()
  })
  if (host.value) resize.observe(host.value)
  document.addEventListener('visibilitychange', onVisibility)
  render()
})
watch(() => [props.visible, props.index], render)
watch(() => props.expanded, render)
watch(() => props.selectedId, highlight)
onUnmounted(() => {
  disposed = true
  motion?.destroy()
  resize?.disconnect()
  preference?.removeEventListener('change', onPreference)
  document.removeEventListener('visibilitychange', onVisibility)
  cy?.destroy()
})
defineExpose({ fit, zoom, focus })
</script>

<template>
  <div ref="sky" class="sky" :class="{ 'is-dragging': dragging, 'is-hovering': hovering, 'is-still': reduced }" @pointermove="parallax" @pointerleave="resetParallax">
    <div aria-hidden="true" class="nebula" />
    <div aria-hidden="true" class="firmament"><i v-for="(s, i) in stars" :key="i" :style="s" /></div>
    <div ref="aura" aria-hidden="true" class="stellar-aura"><span class="aura-ring" /></div>
    <div ref="host" class="graph-host" role="img" aria-label="Bản đồ tri thức cá nhân dạng chòm sao. Chạm một nhóm để mở các mục bên trong; dùng bảng chi tiết bên dưới để duyệt bằng bàn phím." />
    <Transition name="hint">
      <span v-if="hinted || dragging" class="gesture-hint" :class="{ active: dragging }" aria-live="polite">{{ dragging ? 'Chòm sao đang chuyển động' : 'Chạm để mở nhánh · Kéo để lay chuyển' }}</span>
    </Transition>
  </div>
</template>

<style scoped>
.sky {
  --parallax-x: 0px;
  --parallax-y: 0px;
  position: relative;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  isolation: isolate;
  background: radial-gradient(ellipse at 50% 50%, #23232b66, transparent 68%), #101216;
}
.firmament, .graph-host, .nebula { position: absolute; inset: 0; }
.graph-host { cursor: grab; animation: sky-arrive 900ms ease-out both; touch-action: none; }
.is-hovering .graph-host { cursor: pointer; }
.is-dragging .graph-host { cursor: grabbing; }
.firmament { pointer-events: none; transform: translate(var(--parallax-x), var(--parallax-y)); transition: transform 1.2s cubic-bezier(.2,.8,.2,1); }
.firmament i { position: absolute; aspect-ratio: 1; background: #eee4cf; border-radius: 50%; box-shadow: 0 0 6px #eee4cf55; opacity: var(--brightness); animation: twinkle var(--twinkle) ease-in-out infinite alternate; }
.nebula { pointer-events: none; inset: -18%; background: radial-gradient(ellipse at 28% 40%, #b7a9d00e, transparent 45%), radial-gradient(ellipse at 72% 58%, #d4b77d0e, transparent 40%), radial-gradient(ellipse at 50% 85%, #8fc3d40a, transparent 40%); animation: nebula-drift 26s ease-in-out infinite alternate; }
.stellar-aura { --halo-x: -200px; --halo-y: -200px; --halo-color: #d4b77d; position: absolute; pointer-events: none; left: 0; top: 0; width: 150px; height: 150px; border-radius: 50%; transform: translate(calc(var(--halo-x) - 75px), calc(var(--halo-y) - 75px)); background: radial-gradient(circle, color-mix(in srgb, var(--halo-color) 14%, transparent), transparent 65%); opacity: 0; transition: opacity 500ms ease; }
.is-hovering .stellar-aura, .is-dragging .stellar-aura { opacity: 1; }
.aura-ring { position: absolute; inset: 39px; border: 1px solid color-mix(in srgb, var(--halo-color) 30%, transparent); border-radius: 50%; animation: stellar-breathe 3s ease-in-out infinite; }
.gesture-hint { position: absolute; top: 14px; left: 50%; transform: translateX(-50%); pointer-events: none; white-space: nowrap; padding: 6px 12px; border: 1px solid #cbb68b14; border-radius: 20px; background: #13151b99; font-size: 10px; color: #9f998c; transition: color 300ms, background 300ms, border-color 300ms; }
.gesture-hint.active { color: #ead6ae; background: #302a2080; border-color: #cbb68b35; }
.hint-enter-active, .hint-leave-active { transition: opacity 400ms ease, transform 400ms ease; }
.hint-enter-from, .hint-leave-to { opacity: 0; transform: translate(-50%, -6px); }
@keyframes twinkle { from { opacity: calc(var(--brightness) * .45); } to { opacity: var(--brightness); } }
@keyframes nebula-drift { from { transform: translate(-1%, -1%) rotate(-4deg); } to { transform: translate(2%, 1%) rotate(4deg); } }
@keyframes stellar-breathe { 0%,100% { transform: scale(.9); opacity: .35; } 50% { transform: scale(1.12); opacity: .8; } }
@keyframes sky-arrive { from { opacity: 0; } to { opacity: 1; } }
@media (prefers-reduced-motion: reduce) {
  .graph-host, .firmament i, .nebula, .aura-ring { animation: none; }
  .firmament, .stellar-aura, .gesture-hint { transition: none; }
}
.is-still .firmament { transform: none; }
</style>
