<script setup lang="ts">
import { onMounted, onUnmounted, shallowRef, useTemplateRef, watch } from 'vue'
import cytoscape, { type Core, type NodeSingular, type Position } from 'cytoscape'
import type { KnowledgeGraph, KnowledgeNode } from '@/types/knowledge'
import { constellationKinds } from '@/types/knowledge'
import { createConstellationMotion } from './constellationMotion'

const props = defineProps<{ graph: KnowledgeGraph; selectedId?: string }>()
const emit = defineEmits<{ select: [node: KnowledgeNode] }>()
const host = useTemplateRef<HTMLDivElement>('host')
const sky = useTemplateRef<HTMLDivElement>('sky')
const aura = useTemplateRef<HTMLDivElement>('aura')
const dragging = shallowRef(false)
const hovering = shallowRef(false)
const reduced = shallowRef(false)
let cy: Core | undefined
let motion: ReturnType<typeof createConstellationMotion> | undefined
let resize: ResizeObserver | undefined
let preference: MediaQueryList | undefined
let focused: NodeSingular | undefined
let topology = ''
let initialLayout = false
let queued = false
let disposed = false
const positions = new Map<string, Position>()

const stars = Array.from({ length: 100 }, (_, i) => ({
  left: `${(i * 73.137) % 100}%`, top: `${(i * 47.391) % 100}%`,
  '--brightness': .16 + (i % 6) * .075, '--twinkle': `${4 + i % 7}s`,
  animationDelay: `${-(i % 13)}s`, width: `${i % 9 === 0 ? 2 : 1}px`,
}))

function star(color: string) {
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 80 80"><defs><radialGradient id="g"><stop stop-color="${color}" stop-opacity=".6"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></radialGradient></defs><circle cx="40" cy="40" r="38" fill="url(#g)"/><path d="M40 12L42 37L64 40L42 43L40 68L38 43L16 40L38 37Z" fill="${color}" opacity=".85"/><circle cx="40" cy="40" r="3" fill="#fffaf0"/></svg>`)
}

function remember() {
  cy?.nodes().forEach(node => { positions.set(node.id(), { ...node.position() }) })
  // Keep positions for temporary filters without growing across unlimited data.
  while (positions.size > 200) positions.delete(positions.keys().next().value!)
}

function render() {
  if (!cy || disposed) return
  if (motion?.dragging) { queued = true; return }
  const graph = props.graph
  const ids = new Set(graph.nodes.map(node => node.id))
  const edges = graph.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target))
    .map(edge => ({ ...edge, id: `edge:${JSON.stringify([edge.source, edge.target, edge.label])}` }))
  const nextTopology = JSON.stringify([Array.from(ids).sort(), edges.map(edge => edge.id).sort()])
  const changed = nextTopology !== topology
  if (changed) { motion?.stop(); remember() }
  const first = !initialLayout && graph.nodes.length > 0
  cy.batch(() => {
    const retained = new Set([...ids, ...edges.map(edge => edge.id)])
    cy!.elements().filter(element => !retained.has(element.id())).remove()
    graph.nodes.forEach((node, index) => {
      const color = constellationKinds[node.kind]?.color ?? '#eee4cf'
      const data = { id: node.id, label: node.label, kind: node.kind, color, star: star(color) }
      const existing = cy!.getElementById(node.id)
      if (existing.length) { existing.data(data); return }
      const neighbourEdge = edges.find(edge => edge.source === node.id || edge.target === node.id)
      const neighbourId = neighbourEdge?.source === node.id ? neighbourEdge.target : neighbourEdge?.source
      const neighbour = neighbourId ? cy!.getElementById(neighbourId) : undefined
      const origin = neighbour?.length ? neighbour.position() : { x: cy!.width() / 2, y: cy!.height() / 2 }
      const angle = index * 2.39996
      const radius = first ? 60 + Math.sqrt(index) * 35 : 90
      const position = positions.get(node.id) ?? { x: origin.x + Math.cos(angle) * radius, y: origin.y + Math.sin(angle) * radius }
      cy!.add({ group: 'nodes', data, position })
    })
    for (const edge of edges) {
      if (cy!.getElementById(edge.id).empty()) cy!.add({ group: 'edges', data: edge })
    }
  })
  topology = nextTopology
  if (first) {
    cy.layout({ name: 'cose', animate: false, padding: 70, nodeRepulsion: () => 180000, idealEdgeLength: () => 110, randomize: false }).run()
    initialLayout = true
  }
  highlight()
}

function highlight() {
  if (!cy) return
  cy.batch(() => {
    cy!.elements().removeClass('chosen connected muted')
    if (!props.selectedId) return
    const node = cy!.getElementById(props.selectedId)
    if (node.empty()) return
    cy!.elements().addClass('muted')
    node.closedNeighborhood().removeClass('muted').addClass('connected')
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
  cy?.style().selector('node').style('transition-duration', reduced.value ? 0 : 240).update()
}

function onVisibility() { if (document.hidden) { motion?.stop(); hovering.value = false } }
function fit() {
  if (!cy || !cy.nodes().length || motion?.dragging) return
  if (reduced.value) cy.fit(undefined, 65)
  else cy.stop().animate({ fit: { eles: cy.elements(), padding: 65 } }, { duration: 550, easing: 'ease-out-cubic' })
}
function zoom(factor: number) {
  if (!cy || motion?.dragging) return
  const level = Math.max(cy.minZoom(), Math.min(cy.maxZoom(), cy.zoom() * factor))
  const center = { x: cy.width() / 2, y: cy.height() / 2 }
  const pan = { x: center.x - (center.x - cy.pan().x) * level / cy.zoom(), y: center.y - (center.y - cy.pan().y) * level / cy.zoom() }
  if (reduced.value) cy.viewport({ zoom: level, pan })
  else cy.stop().animate({ zoom: level, pan }, { duration: 300, easing: 'ease-out-cubic' })
}

onMounted(() => {
  preference = window.matchMedia('(prefers-reduced-motion: reduce)')
  reduced.value = preference.matches
  preference.addEventListener('change', onPreference)
  cy = cytoscape({ container: host.value!, minZoom: .25, maxZoom: 2.5, wheelSensitivity: .15,
    boxSelectionEnabled: false, selectionType: 'single',
    style: [
      { selector: 'node', style: { width: 48, height: 48, 'background-opacity': 0, 'background-image': 'data(star)', 'background-fit': 'contain', label: 'data(label)', color: '#c6c3bd', 'font-size': 11, 'font-family': 'Geist, sans-serif', 'text-valign': 'bottom', 'text-margin-y': 2, 'text-max-width': '110px', 'text-wrap': 'ellipsis', 'text-outline-width': 3, 'text-outline-color': '#101216', 'overlay-opacity': 0, 'underlay-color': 'data(color)', 'underlay-opacity': 0, 'underlay-padding': 9, 'transition-property': 'width, height, opacity, underlay-opacity', 'transition-duration': reduced.value ? 0 : 240, 'transition-timing-function': 'ease-out-cubic' } },
      { selector: 'node[kind="User"]', style: { width: 80, height: 80, 'font-size': 13, color: '#fff1ce' } },
      { selector: 'edge', style: { width: .8, 'line-color': '#968b76', opacity: .38, 'curve-style': 'unbundled-bezier', 'control-point-distances': 14, 'control-point-weights': .5, 'target-arrow-shape': 'none', 'transition-property': 'opacity, line-color, width', 'transition-duration': reduced.value ? 0 : 260 } },
      { selector: '.muted', style: { opacity: .26 } },
      { selector: 'node.chosen', style: { 'underlay-opacity': .09, color: '#fff3d5' } },
      { selector: 'node.hovered, node.held', style: { width: 60, height: 60, 'underlay-opacity': .13, color: '#fff3d5', 'z-index': 20 } },
      { selector: 'node[kind="User"].hovered, node[kind="User"].held', style: { width: 88, height: 88 } },
      { selector: 'edge.connected, edge.hovered', style: { width: 1.35, opacity: .85, 'line-color': '#d4b77d' } },
      { selector: 'edge.tethered', style: { width: 1.6, opacity: .95, 'line-color': '#e8cf9b' } },
      { selector: 'node.tethered', style: { opacity: 1 } },
    ],
  })
  motion = createConstellationMotion(cy, {
    reduced: () => reduced.value,
    onDrag(active, node) {
      dragging.value = active
      if (node) { focused = node; follow(node) }
      if (!active) {
        remember()
        if (queued) { queued = false; queueMicrotask(render) }
      }
    },
    onFrame: follow,
  })
  cy.on('mouseover', 'node', event => {
    focused = event.target
    hovering.value = true
    focused!.addClass('hovered')
    focused!.connectedEdges().addClass('hovered')
    follow(focused!)
  })
  cy.on('mouseout', 'node', event => {
    event.target.removeClass('hovered').connectedEdges().removeClass('hovered')
    hovering.value = false
  })
  cy.on('pan zoom', () => { if (focused) follow(focused) })
  cy.on('tap', 'node', event => {
    const node = props.graph.nodes.find(n => n.id === event.target.id())
    if (node) emit('select', node)
  })
  resize = new ResizeObserver(() => cy?.resize())
  if (host.value) resize.observe(host.value)
  document.addEventListener('visibilitychange', onVisibility)
  render()
})
watch(() => props.graph, render)
watch(() => props.selectedId, highlight)
onUnmounted(() => {
  disposed = true
  motion?.destroy()
  resize?.disconnect()
  preference?.removeEventListener('change', onPreference)
  document.removeEventListener('visibilitychange', onVisibility)
  cy?.destroy()
})
defineExpose({ fit, zoom })
</script>

<template>
  <div ref="sky" class="sky" :class="{ 'is-dragging': dragging, 'is-hovering': hovering, 'is-still': reduced }" @pointermove="parallax" @pointerleave="resetParallax">
    <div aria-hidden="true" class="nebula" />
    <div aria-hidden="true" class="firmament"><i v-for="(s, i) in stars" :key="i" :style="s" /></div>
    <div aria-hidden="true" class="celestial-circle"><span>N</span><span>E</span><span>S</span><span>W</span></div>
    <div ref="aura" aria-hidden="true" class="stellar-aura"><span class="aura-ring" /></div>
    <div ref="host" class="graph-host" role="img" aria-label="Bản đồ chòm sao tri thức cá nhân. Kéo một sao để chuyển động các sao liên kết. Dùng danh sách bên dưới để chọn bằng bàn phím." />
    <span class="sky-caption">OLYMPUS · PERSONAL COSMOS</span>
    <span v-if="graph.nodes.length" class="gesture-hint" :class="{ active: dragging }" aria-live="polite">{{ dragging ? 'Chòm sao đang chuyển động' : 'Kéo một vì sao · Khám phá liên kết' }}</span>
  </div>
</template>

<style scoped>
.sky {
  --parallax-x: 0px;
  --parallax-y: 0px;
  position: relative;
  height: 100%;
  min-height: 300px;
  overflow: hidden;
  isolation: isolate;
  background: radial-gradient(ellipse at 48% 48%, #24242b55, transparent 65%), #101216;
}
.firmament, .graph-host, .nebula { position: absolute; inset: 0; }
.graph-host { cursor: grab; animation: sky-arrive 900ms ease-out both; touch-action: none; }
.is-hovering .graph-host { cursor: pointer; }
.is-dragging .graph-host { cursor: grabbing; }
.firmament { pointer-events: none; transform: translate(var(--parallax-x), var(--parallax-y)); transition: transform 1.2s cubic-bezier(.2,.8,.2,1); }
.firmament i { position: absolute; aspect-ratio: 1; background: #eee4cf; border-radius: 50%; box-shadow: 0 0 6px #eee4cf55; opacity: var(--brightness); animation: twinkle var(--twinkle) ease-in-out infinite alternate; }
.nebula { pointer-events: none; inset: -18%; background: radial-gradient(ellipse at 28% 40%, #b7a9d00c, transparent 45%), radial-gradient(ellipse at 72% 58%, #d4b77d0c, transparent 40%); animation: nebula-drift 24s ease-in-out infinite alternate; }
.celestial-circle { position: absolute; pointer-events: none; width: 78%; aspect-ratio: 1; border: 1px solid #d4b77d12; border-radius: 50%; left: 11%; top: 50%; transform: translateY(-50%); box-shadow: 0 0 0 24px #d4b77d03, 0 0 0 25px #d4b77d0a; }
.celestial-circle span { position: absolute; font: 9px 'JetBrains Mono',monospace; color: #a89b7455; }
.celestial-circle span:nth-child(1) { left: 50%; top: -18px; }
.celestial-circle span:nth-child(2) { right: -17px; top: 50%; }
.celestial-circle span:nth-child(3) { left: 50%; bottom: -18px; }
.celestial-circle span:nth-child(4) { left: -17px; top: 50%; }
.stellar-aura { --halo-x: -200px; --halo-y: -200px; --halo-color: #d4b77d; position: absolute; pointer-events: none; left: 0; top: 0; width: 150px; height: 150px; border-radius: 50%; transform: translate(calc(var(--halo-x) - 75px), calc(var(--halo-y) - 75px)); background: radial-gradient(circle, color-mix(in srgb, var(--halo-color) 12%, transparent), transparent 65%); opacity: 0; transition: opacity 500ms ease; }
.is-hovering .stellar-aura, .is-dragging .stellar-aura { opacity: 1; }
.aura-ring { position: absolute; inset: 39px; border: 1px solid color-mix(in srgb, var(--halo-color) 28%, transparent); border-radius: 50%; animation: stellar-breathe 3s ease-in-out infinite; }
.sky-caption { position: absolute; bottom: 18px; left: 22px; pointer-events: none; font: 8px 'JetBrains Mono',monospace; letter-spacing: .18em; color: #77736a; }
.gesture-hint { position: absolute; top: 16px; left: 50%; transform: translateX(-50%); pointer-events: none; white-space: nowrap; padding: 7px 12px; border: 1px solid #cbb68b12; border-radius: 20px; background: #13151b80; font-size: 10px; color: #9f998c; transition: color 300ms, background 300ms, border-color 300ms; }
.gesture-hint.active { color: #ead6ae; background: #302a2080; border-color: #cbb68b35; }
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
