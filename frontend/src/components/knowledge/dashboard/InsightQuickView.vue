<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, useId, useTemplateRef } from 'vue'
import { ArrowUpRight, X } from 'lucide-vue-next'
import { hubColor, type KnowledgeGraph, type KnowledgeInsight } from '@/types/knowledge'
import NutritionDetail from './NutritionDetail.vue'

const props = defineProps<{ graph: KnowledgeGraph; insight: KnowledgeInsight }>()
const emit = defineEmits<{ close: []; explore: [id: string] }>()
const dialog = useTemplateRef<HTMLDialogElement>('dialog')
const titleId = useId()
const items = computed(() => props.graph.nodes.filter(node => node.hub === props.insight.hub && ['Goal', 'BodyMetric', 'Training', 'Intent'].includes(node.kind)).slice(0, 8))
onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => dialog.value?.close())

function close() { dialog.value?.close(); emit('close') }
function explore(id: string) { close(); emit('explore', id) }
function backdrop(event: MouseEvent) {
  if (!dialog.value || event.target !== dialog.value) return
  const bounds = dialog.value.getBoundingClientRect()
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) close()
}
</script>

<template>
  <dialog ref="dialog" class="quick-view" :style="{ '--accent': hubColor(insight.hub) }" :aria-labelledby="titleId" @cancel.prevent="close" @keydown.esc.stop @click="backdrop">
    <header class="quick-head"><div><p>XEM NHANH</p><h3 :id="titleId">{{ insight.title }}</h3></div><button type="button" class="close-button" autofocus aria-label="Đóng xem nhanh" @click="close"><X :size="18" /></button></header>
    <div class="quick-content">
      <NutritionDetail v-if="insight.hub === 'nutrition'" :graph="graph" @explore="explore" />
      <template v-else><div class="quick-summary"><strong>{{ insight.value }}</strong><span>{{ insight.caption }}</span><p v-if="insight.detail">{{ insight.detail }}</p></div>
        <div v-if="items.length" class="records"><article v-for="item in items" :key="item.id"><button type="button" @click="explore(item.id)"><span>{{ item.label }}</span><ArrowUpRight :size="14" /></button><p v-if="item.summary">{{ item.summary }}</p><dl><div v-for="fact in item.details" :key="fact.label"><dt>{{ fact.label }}</dt><dd>{{ fact.value }}</dd></div></dl></article></div>
        <p v-else class="empty">Chưa có bản ghi chi tiết. Dữ liệu sẽ xuất hiện khi bạn cập nhật qua trò chuyện.</p>
        <button class="map-link" type="button" @click="explore('hub:' + insight.hub)">Khám phá trên bản đồ <ArrowUpRight :size="14" /></button>
      </template>
    </div>
  </dialog>
</template>

<style scoped>
.quick-view { position: fixed; width: min(470px, calc(100vw - 32px)); max-height: min(780px, calc(100dvh - 48px)); margin: auto; padding: 0; overflow-y: auto; overscroll-behavior: contain; color: #e8e6de; background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 6%, #171a20), #14171c 50%); border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent); border-radius: 22px; box-shadow: 0 30px 100px #0009, 0 0 0 6px #ffffff03; font-family: Geist, sans-serif; }
.quick-view[open] { animation: pop-in 260ms cubic-bezier(.2,.8,.2,1); }
.quick-view::backdrop { background: #080b12a6; backdrop-filter: blur(5px); animation: fade-in 220ms ease-out; }
.quick-head { position: sticky; top: 0; z-index: 3; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 22px 24px 17px; border-bottom: 1px solid #ffffff0d; background: #171b20f5; backdrop-filter: blur(12px); }
.quick-head p { margin: 0 0 6px; font: 9px 'JetBrains Mono', monospace; letter-spacing: .17em; color: var(--accent); }.quick-head h3 { margin: 0; font: 27px 'Playfair Display', serif; color: #f2eddf; }
.close-button { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; color: #b5b8ae; background: #ffffff05; border: 1px solid #ffffff14; transition: background 160ms, transform 160ms; }.close-button:hover { background: #ffffff10; transform: rotate(90deg); }
.quick-content { padding: 22px 24px 24px; }.quick-summary { padding-bottom: 20px; }.quick-summary > strong { display: block; font: 30px 'Playfair Display', serif; color: var(--accent); }.quick-summary > span, .quick-summary p { font-size: 12px; color: #aaa99f; line-height: 1.6; }.quick-summary p { margin: 8px 0 0; }
.records { display: flex; flex-direction: column; gap: 12px; }.records article { padding: 14px; border-radius: 12px; border: 1px solid #ffffff0e; background: #ffffff02; }.records article > button { display: flex; justify-content: space-between; align-items: center; gap: 10px; width: 100%; text-align: left; color: var(--accent); font-size: 12px; }.records article > button svg { flex-shrink: 0; }.records p { font-size: 11px; color: #a4a69a; line-height: 1.6; }.records dl { display: flex; flex-direction: column; gap: 7px; margin: 10px 0 0; }.records dl > div { display: flex; justify-content: space-between; gap: 15px; font-size: 11px; }.records dt { color: #9d9f95; }.records dd { margin: 0; color: #d6d7ce; text-align: right; overflow-wrap: anywhere; }
.map-link { display: flex; align-items: center; justify-content: center; gap: 8px; width: 100%; padding: 12px; margin-top: 20px; color: var(--accent); border: 1px solid color-mix(in srgb, var(--accent) 25%, transparent); border-radius: 10px; font-size: 12px; }.map-link:hover { background: #ffffff05; }.empty { font-size: 12px; color: #a4a69a; line-height: 1.7; }
@keyframes pop-in { from { opacity: 0; transform: translateY(14px) scale(.96); } }@keyframes fade-in { from { opacity: 0; } }
@media (max-width: 420px) { .quick-head { padding: 18px; }.quick-content { padding: 18px; } }
@media (prefers-reduced-motion: reduce) { .quick-view[open], .quick-view::backdrop { animation: none; }.close-button { transition: none; }.close-button:hover { transform: none; } }
</style>
