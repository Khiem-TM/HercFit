<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { ChevronRight, Maximize2 } from 'lucide-vue-next'
import type { KnowledgeNode } from '@/types/knowledge'
import { hubColor, kindLabels, ROOT_COLOR } from '@/types/knowledge'
import ImageLightbox from './ImageLightbox.vue'
import { mediaCaption, mediaTarget, sizedImage } from './knowledgeMedia'
import { ancestors, type TreeIndex } from './knowledgeTree'
import { useNodeImage } from './useNodeImage'

const props = defineProps<{ node?: KnowledgeNode; index: TreeIndex; expanded: ReadonlySet<string>; roomy?: boolean }>()
const emit = defineEmits<{ select: [id: string]; toggle: [id: string]; expand: [] }>()

const color = computed(() => (props.node?.kind === 'User' ? ROOT_COLOR : hubColor(props.node?.hub)))
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
            <small>{{ item.label }}</small>{{ item.node.label }}
          </button>
        </div>
      </div>
      <Teleport to="body">
        <ImageLightbox v-if="zoomed && url" :src="url" :alt="`${caption}: ${node.label}`" :caption="`${caption} · ${node.label}`"
                       :accent="color" @close="zoomed = false" />
      </Teleport>
    </template>
    <template v-else>
      <p class="eyeline"><i />KHÁM PHÁ CHÒM SAO</p>
      <h3>Chạm một vì sao để mở câu chuyện.</h3>
      <p class="summary">Nhóm có viền nét đứt còn chứa mục bên trong: chạm để mở nhánh, chạm lần nữa để thu gọn. Kéo thanh phía trên khung này để đọc chi tiết rộng hơn.</p>
    </template>
  </section>
</template>

<style scoped>
.inspector { --accent: #d4b77d; container: inspector / inline-size; padding: 14px var(--gutter, 24px) 18px; overflow-y: auto; overscroll-behavior: contain; animation: rise 360ms cubic-bezier(.2,.8,.2,1) both; }
.trail { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; margin-bottom: 10px; font-size: 10px; color: #6f6c65; }
.trail button { color: #a7a196; transition: color 200ms; }
.trail button:hover { color: #f0e3c4; }
.trail span { color: #d8cfbc; }
.lead { display: grid; gap: 14px; }
.lead.with-media { grid-template-areas: "media" "facts"; }
.facts { grid-area: facts; min-width: 0; }
.eyeline { display: flex; align-items: center; gap: 7px; font: 8px 'JetBrains Mono', monospace; letter-spacing: .2em; text-transform: uppercase; color: color-mix(in srgb, var(--accent) 80%, #fff); margin: 0 0 8px; }
.eyeline i { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 10px var(--accent); }
h3 { font: 19px 'Playfair Display', serif; font-weight: 400; color: #f2eadb; margin: 0 0 6px; letter-spacing: -.01em; transition: font-size 260ms; }
.summary { font-size: 11px; color: #9a968c; line-height: 1.6; margin: 0 0 12px; }
dl { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px 16px; margin: 0 0 12px; }
dt, dd { margin: 0; }
dt { font-size: 9px; color: #7f7c74; text-transform: uppercase; letter-spacing: .06em; }
dd { font-size: 12px; color: #e4ddcf; margin-top: 2px; overflow-wrap: anywhere; }
.media { grid-area: media; margin: 0; min-width: 0; opacity: 0; transform: translateY(6px); transition: opacity 420ms ease, transform 420ms cubic-bezier(.2,.8,.2,1); }
.media.ready { opacity: 1; transform: none; }
.frame { position: relative; display: block; width: 100%; aspect-ratio: 16 / 10; max-height: 200px; overflow: hidden; border-radius: 12px; border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent); background: #0c0d11; cursor: zoom-in; box-shadow: 0 10px 30px #0004; transition: max-height 320ms cubic-bezier(.2,.8,.2,1); }
.frame img { display: block; width: 100%; height: 100%; object-fit: cover; transition: transform 700ms cubic-bezier(.2,.8,.2,1); }
.frame:hover img, .frame:focus-visible img { transform: scale(1.04); }
.frame:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
.zoom-hint { position: absolute; right: 8px; bottom: 8px; display: inline-flex; align-items: center; gap: 5px; padding: 4px 9px; border-radius: 12px; background: #0e1014cc; color: #efe3c4; font-size: 10px; opacity: 0; transition: opacity 200ms; backdrop-filter: blur(6px); }
.frame:hover .zoom-hint, .frame:focus-visible .zoom-hint { opacity: 1; }
figcaption { margin-top: 6px; font-size: 10px; color: #8d8a82; }
.branch { border-top: 1px solid #ffffff0a; padding-top: 10px; margin-top: 4px; }
.branch-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; font-size: 10px; color: #8d8a82; }
.toggle { font-size: 10px; color: color-mix(in srgb, var(--accent) 85%, #fff); padding: 4px 10px; border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent); border-radius: 20px; transition: background 200ms; }
.toggle:hover { background: color-mix(in srgb, var(--accent) 12%, transparent); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chips button { display: flex; align-items: center; gap: 6px; max-width: 100%; padding: 5px 10px; border: 1px solid #ffffff0e; border-radius: 16px; font-size: 10px; color: #c9c4b8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; transition: border-color 200ms, color 200ms, background 200ms; }
.chips button:hover { border-color: color-mix(in srgb, var(--accent) 45%, transparent); color: #f1e6cb; background: #ffffff05; }
.chips i { width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; }
.chips small { font: 9px 'JetBrains Mono', monospace; color: #8a867c; }
.chips .linked small { color: #c8ad74; }
.chips .more { border-style: dashed; color: color-mix(in srgb, var(--accent) 80%, #fff); }
.roomy h3 { font-size: 23px; }
.roomy .summary { font-size: 12px; }
.roomy dd { font-size: 13px; }
.roomy .frame { max-height: min(46vh, 420px); }
@container inspector (min-width: 560px) {
  .lead.with-media { grid-template-columns: minmax(0, 1fr) minmax(200px, 40%); grid-template-areas: "facts media"; align-items: start; gap: 22px; }
  .lead.with-media .frame { aspect-ratio: 4 / 3; max-height: 240px; }
  .roomy .lead.with-media .frame { max-height: min(52vh, 460px); }
}
@container inspector (min-width: 900px) {
  .roomy .lead.with-media { grid-template-columns: minmax(0, 1fr) minmax(280px, 46%); }
}
@keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
  .inspector { animation: none; }
  .media, .frame, .frame img, h3 { transition: none; }
  .frame:hover img, .frame:focus-visible img { transform: none; }
}
</style>
