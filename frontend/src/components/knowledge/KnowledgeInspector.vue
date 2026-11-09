<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { ChevronRight, Maximize2 } from 'lucide-vue-next'
import type { KnowledgeNode } from '@/types/knowledge'
import { hubColor, kindLabels } from '@/types/knowledge'
import ImageLightbox from './ImageLightbox.vue'
import { mediaCaption, mediaTarget, sizedImage } from './knowledgeMedia'
import { ancestors, type TreeIndex } from './knowledgeTree'
import { useNodeImage } from './useNodeImage'

const props = defineProps<{ node?: KnowledgeNode; index: TreeIndex; expanded: ReadonlySet<string>; roomy?: boolean }>()
const emit = defineEmits<{ select: [id: string]; toggle: [id: string]; expand: [] }>()

const color = computed(() => hubColor(props.node?.kind === 'User' ? null : props.node?.hub))
const trail = computed(() => props.node ? ancestors(props.index, props.node.id).map(id => props.index.byId.get(id)).filter(Boolean) as KnowledgeNode[] : [])
const children = computed(() => props.node ? (props.index.children.get(props.node.id) ?? []).map(id => props.index.byId.get(id)!).filter(Boolean) : [])
const shownChildren = computed(() => props.roomy ? children.value : children.value.slice(0, 18))
const related = computed(() => {
  if (!props.node) return []
  const id = props.node.id
  return props.index.links
    .filter(link => link.source === id || link.target === id)
    .map(link => ({ label: link.label, node: props.index.byId.get(link.source === id ? link.target : link.source) }))
    .filter((item): item is { label: string | null; node: KnowledgeNode } => !!item.node)
    .slice(0, props.roomy ? 40 : 12)
})
const open = computed(() => !!props.node && (props.node.kind === 'User' || props.expanded.has(props.node.id)))

const target = computed(() => props.node ? mediaTarget(props.node.id) : null)
const { url } = useNodeImage(() => target.value)
const ready = shallowRef(false)
const failed = shallowRef(false)
const zoomed = shallowRef(false)
const caption = computed(() => {
  const value = target.value
  if (!value) return ''
  if (!value.inherited) return mediaCaption[value.kind]
  return value.kind === 'meals' ? 'Ảnh của bữa ăn chứa món này' : 'Ảnh của buổi tập chứa bài này'
})
const showMedia = computed(() => Boolean(url.value && !failed.value))
</script>

<template>
  <section class="inspector" :class="{ roomy }" :style="{ '--accent': color }" aria-live="polite">
    <template v-if="node">
      <nav v-if="trail.length" class="trail" aria-label="Vị trí trên bản đồ">
        <template v-for="item in trail" :key="item.id">
          <button type="button" @click="emit('select', item.id)">{{ item.label }}</button>
          <ChevronRight :size="11" aria-hidden="true" />
        </template>
        <span aria-current="true">{{ node.label }}</span>
      </nav>
      <div class="lead" :class="{ 'with-media': showMedia }">
        <div class="facts">
          <p class="eyeline"><i />{{ kindLabels[node.kind] ?? node.kind }}</p>
          <h3>{{ node.label }}</h3>
          <p v-if="node.summary" class="summary">{{ node.summary }}</p>
          <dl v-if="node.details.length">
            <div v-for="detail in node.details" :key="detail.label" class="pair"><dt>{{ detail.label }}</dt><dd>{{ detail.value }}</dd></div>
          </dl>
        </div>
        <figure v-if="showMedia && url" class="media" :class="{ ready }">
          <button type="button" class="frame" :aria-label="`Phóng to ${caption.toLocaleLowerCase('vi')}`" @click="zoomed = true">
            <img :src="sizedImage(url, 960)" :alt="`${caption}: ${node.label}`" decoding="async" referrerpolicy="no-referrer"
                 @load="ready = true" @error="failed = true" />
            <span class="zoom-hint" aria-hidden="true"><Maximize2 :size="12" /> Phóng to</span>
          </button>
          <figcaption>{{ caption }}</figcaption>
        </figure>
      </div>
      <div v-if="children.length" class="branch">
        <div class="branch-head">
          <span>{{ children.length }} mục bên trong</span>
          <button v-if="node.kind !== 'User'" type="button" class="toggle" :aria-expanded="open" @click="emit('toggle', node.id)">
            {{ open ? 'Thu gọn nhánh' : 'Mở nhánh trên bản đồ' }}
          </button>
        </div>
        <div class="chips">
          <button v-for="child in shownChildren" :key="child.id" type="button" @click="emit('select', child.id)">
            <i :style="{ background: hubColor(child.hub) }" />{{ child.label }}<small v-if="child.children">+{{ child.children }}</small>
          </button>
          <button v-if="children.length > shownChildren.length" type="button" class="more" @click="emit('expand')">
            Xem thêm {{ children.length - shownChildren.length }} mục
          </button>
        </div>
      </div>
      <div v-if="related.length" class="branch">
        <div class="branch-head"><span>Liên kết</span></div>
        <div class="chips">
          <button v-for="item in related" :key="item.node.id" type="button" class="linked" @click="emit('select', item.node.id)">
            <span class="linked-name"><i :style="{ background: hubColor(item.node.hub) }" />{{ item.node.label }}</span><small>{{ item.label }}</small>
          </button>
        </div>
      </div>
      <Teleport to="body">
        <ImageLightbox v-if="zoomed && url" :src="url" :alt="`${caption}: ${node.label}`" :caption="`${caption} · ${node.label}`"
                       :accent="color" @close="zoomed = false" />
      </Teleport>
    </template>
    <template v-else>
      <p class="eyeline"><i />Trung tâm</p>
      <h3>Chọn một nút trên bản đồ</h3>
      <p class="summary">Chạm một nhóm để mở các mục bên trong, chạm lần nữa để thu gọn. Chi tiết, nguồn và liên kết của mục đang chọn hiện ở đây.</p>
    </template>
  </section>
</template>

<style scoped>
.inspector { --accent: var(--hf-ink); container: inspector / inline-size; display: flex; flex-direction: column; gap: 4px; min-width: 0; animation: rise 300ms cubic-bezier(.2, .8, .2, 1) both; }
.trail { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; font-size: 12px; color: var(--hf-muted); }
.trail button { border: 0; background: transparent; padding: 0; color: var(--hf-sub-2); font-size: 12px; }
.trail button:hover { color: var(--hf-ink); text-decoration: underline; }
.trail span { color: var(--hf-ink); font-weight: 600; }
.lead { display: grid; gap: 14px; grid-template-areas: "facts"; }
.lead.with-media { grid-template-areas: "media" "facts"; }
.facts { grid-area: facts; min-width: 0; }
.eyeline { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 500; color: var(--hf-muted); margin: 0 0 10px; }
.eyeline i { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); flex: none; }
h3 { font-size: 26px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.15; color: var(--hf-ink); margin: 0; }
.summary { font-size: 14px; color: var(--hf-muted); line-height: 1.5; margin: 8px 0 12px; }
dl { margin: 0 0 8px; }
.pair { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 16px; padding: 12px 0; border-top: 1px solid var(--hf-line-2); align-items: baseline; }
.pair:first-child { border-top: 0; }
dt, dd { margin: 0; }
dt { font-size: 14px; font-weight: 600; color: var(--hf-ink); }
dd { font-size: 14px; font-weight: 500; color: var(--hf-ink); text-align: right; overflow-wrap: anywhere; }
.media { grid-area: media; margin: 0; min-width: 0; opacity: 0; transform: translateY(6px); transition: opacity 420ms ease, transform 420ms cubic-bezier(.2, .8, .2, 1); }
.media.ready { opacity: 1; transform: none; }
.frame { position: relative; display: block; width: 100%; aspect-ratio: 16 / 10; max-height: 200px; overflow: hidden; border-radius: 16px; border: 1px solid var(--hf-press); background: var(--hf-fill-3); cursor: zoom-in; padding: 0; }
.frame img { display: block; width: 100%; height: 100%; object-fit: cover; transition: transform 700ms cubic-bezier(.2, .8, .2, 1); }
.frame:hover img, .frame:focus-visible img { transform: scale(1.04); }
.zoom-hint { position: absolute; right: 8px; bottom: 8px; display: inline-flex; align-items: center; gap: 5px; padding: 4px 9px; border-radius: 999px; background: var(--hf-card); color: var(--hf-ink); font-size: 11px; opacity: 0; transition: opacity 200ms; }
.frame:hover .zoom-hint, .frame:focus-visible .zoom-hint { opacity: 1; }
figcaption { margin-top: 6px; font-size: 12px; color: var(--hf-muted); }
.branch { border-top: 1px solid var(--hf-line-2); padding-top: 12px; margin-top: 4px; display: flex; flex-direction: column; gap: 8px; }
.branch-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 13px; font-weight: 500; color: var(--hf-muted); }
.toggle { border: 0; background: transparent; padding: 0; min-height: 32px; font-size: 13px; font-weight: 600; text-decoration: underline; text-underline-offset: 2px; color: var(--hf-ink); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chips button { display: flex; align-items: center; gap: 6px; max-width: 100%; min-height: 36px; padding: 0 12px; border: 1px solid var(--hf-line-3); background: var(--hf-card); border-radius: 999px; font-size: 13px; color: var(--hf-ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chips button:hover { background: var(--hf-fill-3); }
.chips i { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.chips small { font-family: var(--hf-mono); font-size: 11px; color: var(--hf-muted); }
.chips .linked { width: 100%; justify-content: space-between; border: 0; background: var(--hf-fill-2); border-radius: 14px; min-height: 44px; padding: 0 14px; }
.chips .linked:hover { background: var(--hf-hover); }
.linked-name { display: inline-flex; align-items: center; gap: 8px; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.chips .linked small { font-family: var(--hf-font); font-size: 12px; }
.chips .more { border-style: dashed; color: var(--hf-sub); }
.roomy .frame { max-height: min(46vh, 420px); }
@container inspector (min-width: 560px) {
  .lead.with-media { grid-template-columns: minmax(0, 1fr) minmax(200px, 40%); grid-template-areas: "facts media"; align-items: start; gap: 22px; }
  .lead.with-media .frame { aspect-ratio: 4 / 3; max-height: 240px; }
}
@keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .inspector { animation: none; }
  .media, .frame, .frame img { transition: none; }
  .frame:hover img, .frame:focus-visible img { transform: none; }
}
</style>
