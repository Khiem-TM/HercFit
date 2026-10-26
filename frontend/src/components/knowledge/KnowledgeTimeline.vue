<script setup lang="ts">
import { computed, ref } from 'vue'
import type { KnowledgeEvent, KnowledgeHub } from '@/types/knowledge'
import { hubColor, hubTheme } from '@/types/knowledge'

const props = defineProps<{ events: KnowledgeEvent[] }>()
const emit = defineEmits<{ explore: [id: string] }>()
const filter = ref<KnowledgeHub | 'all'>('all')
const hubs = Object.keys(hubTheme) as KnowledgeHub[]
const counts = computed(() => Object.fromEntries(hubs.map(hub => [hub, props.events.filter(event => event.hub === hub).length])))

function dayKey(date: Date) {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
}

function heading(date: Date) {
  const today = new Date()
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1)
  if (dayKey(date) === dayKey(today)) return 'Hôm nay'
  if (dayKey(date) === dayKey(yesterday)) return 'Hôm qua'
  const label = date.toLocaleDateString('vi-VN', { weekday: 'long', day: '2-digit', month: '2-digit' })
  return label.charAt(0).toUpperCase() + label.slice(1)
}

const groups = computed(() => {
  const result: { key: string; title: string; events: (KnowledgeEvent & { time: string })[] }[] = []
  for (const event of props.events) {
    if (filter.value !== 'all' && event.hub !== filter.value) continue
    // Goal start dates are days without a time of day.
    const date = new Date(event.at.length === 10 ? `${event.at}T00:00:00` : event.at)
    if (Number.isNaN(date.getTime())) continue
    const key = dayKey(date)
    let group = result.find(item => item.key === key)
    if (!group) result.push(group = { key, title: heading(date), events: [] })
    group.events.push({ ...event, time: event.at.length === 10 ? '—' : date.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }) })
  }
  return result
})
</script>

<template>
  <div class="timeline">
    <div class="filters" role="toolbar" aria-label="Lọc dòng thời gian">
      <button type="button" :class="{ active: filter === 'all' }" @click="filter = 'all'">Tất cả <small>{{ events.length }}</small></button>
      <button v-for="hub in hubs" :key="hub" type="button" :class="{ active: filter === hub }" :disabled="!counts[hub]" @click="filter = hub">
        <i :style="{ background: hubColor(hub) }" />{{ hubTheme[hub].label }} <small>{{ counts[hub] }}</small>
      </button>
    </div>
    <section v-for="group in groups" :key="group.key" class="day">
      <h3>{{ group.title }}</h3>
      <ol>
        <li v-for="event in group.events" :key="event.id" :style="{ '--accent': hubColor(event.hub) }">
          <button type="button" @click="emit('explore', event.node_id)">
            <time>{{ event.time }}</time>
            <span class="dot" aria-hidden="true" />
            <span class="text"><strong>{{ event.title }}</strong><small v-if="event.subtitle">{{ event.subtitle }}</small></span>
            <span class="tag">{{ hubTheme[event.hub]?.label }}</span>
          </button>
        </li>
      </ol>
    </section>
    <p v-if="!groups.length" class="empty">Chưa có hoạt động nào trong nhóm này.</p>
  </div>
</template>

<style scoped>
.timeline { padding: 14px var(--gutter, 26px) 26px; }
.filters { position: sticky; top: 0; z-index: 2; display: flex; gap: 6px; overflow-x: auto; padding: 4px 0 14px; background: linear-gradient(#101216 75%, transparent); }
.filters button { display: flex; align-items: center; gap: 6px; white-space: nowrap; padding: 6px 11px; border: 1px solid #ffffff0d; border-radius: 20px; font-size: 10px; color: #9c998f; transition: color 200ms, border-color 200ms, background 200ms; }
.filters button small { font: 9px 'JetBrains Mono', monospace; color: #6f6c65; }
.filters button i { width: 5px; height: 5px; border-radius: 50%; }
.filters button.active { border-color: #d4b77d55; background: #d4b77d0d; color: #ecdfc3; }
.filters button:disabled { opacity: .35; }
.day { margin-top: 6px; }
.day h3 { position: sticky; top: 44px; z-index: 1; margin: 0; padding: 8px 0; font: 15px 'Playfair Display', serif; font-weight: 400; color: #e9dfca; background: #101216e6; }
ol { list-style: none; margin: 0 0 10px; padding: 0 0 0 4px; border-left: 1px solid #ffffff0d; }
li { --accent: #d4b77d; }
li button { position: relative; display: grid; grid-template-columns: 44px 10px 1fr auto; align-items: start; gap: 10px; width: 100%; padding: 9px 8px 9px 10px; text-align: left; border-radius: 10px; transition: background 200ms; animation: slide-in 420ms cubic-bezier(.2,.8,.2,1) both; }
li button:hover { background: #ffffff06; }
li button:focus-visible { outline: 1px solid var(--accent); }
time { font: 10px 'JetBrains Mono', monospace; color: #8b877e; padding-top: 2px; }
.dot { width: 8px; height: 8px; margin-top: 3px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent), 0 0 12px color-mix(in srgb, var(--accent) 40%, transparent); }
.text { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.text strong { font-size: 12px; font-weight: 500; color: #e6e1d6; }
.text small { font-size: 10px; color: #8c897f; line-height: 1.5; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.tag { font: 8px 'JetBrains Mono', monospace; letter-spacing: .08em; color: color-mix(in srgb, var(--accent) 75%, #fff); padding: 3px 7px; border-radius: 10px; background: color-mix(in srgb, var(--accent) 10%, transparent); white-space: nowrap; }
.empty { font-size: 11px; color: #85847e; text-align: center; padding: 30px 0; }
@keyframes slide-in { from { opacity: 0; transform: translateX(-6px); } to { opacity: 1; transform: none; } }
@container observatory (max-width: 460px) { .tag { display: none; } li button { grid-template-columns: 40px 10px 1fr; } }
@container observatory (min-width: 900px) { .text strong { font-size: 13px; } .text small { font-size: 11px; -webkit-line-clamp: 3; } li button { padding-block: 11px; } }
@media (prefers-reduced-motion: reduce) { li button { animation: none; } }
</style>
