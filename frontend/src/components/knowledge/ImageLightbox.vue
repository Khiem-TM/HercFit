<script setup lang="ts">
import { onBeforeUnmount, onMounted, useId, useTemplateRef } from 'vue'
import { ExternalLink, X } from 'lucide-vue-next'

const props = defineProps<{ src: string; alt: string; caption: string; accent?: string }>()
const emit = defineEmits<{ close: [] }>()
const dialog = useTemplateRef<HTMLDialogElement>('dialog')
const titleId = useId()
const previous = document.activeElement as HTMLElement | null

function close() { dialog.value?.close(); emit('close') }
function backdrop(event: MouseEvent) { if (event.target === dialog.value) close() }
onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => { dialog.value?.close(); previous?.focus() })
</script>

<template>
  <dialog ref="dialog" class="lightbox" :style="{ '--accent': accent ?? '#d4b77d' }" :aria-labelledby="titleId"
          @cancel.prevent="close" @keydown.esc.stop @click="backdrop">
    <figure>
      <img :src="props.src" :alt="alt" decoding="async" referrerpolicy="no-referrer" />
      <figcaption>
        <span :id="titleId">{{ caption }}</span>
        <a :href="props.src" target="_blank" rel="noopener noreferrer">Ảnh gốc <ExternalLink :size="12" aria-hidden="true" /></a>
      </figcaption>
    </figure>
    <button type="button" class="close" autofocus aria-label="Đóng ảnh" @click="close"><X :size="18" /></button>
  </dialog>
</template>

<style scoped>
.lightbox { position: fixed; max-width: min(1100px, calc(100vw - 32px)); max-height: calc(100dvh - 32px); margin: auto; padding: 0; overflow: visible; border: 0; background: transparent; color: #ece4d2; }
.lightbox[open] { animation: zoom-in 260ms cubic-bezier(.2,.8,.2,1); }
.lightbox::backdrop { background: #06080ccc; backdrop-filter: blur(8px); animation: fade 220ms ease-out; }
figure { margin: 0; display: flex; flex-direction: column; gap: 10px; }
img { display: block; max-width: min(1100px, calc(100vw - 32px)); max-height: calc(100dvh - 96px); width: auto; height: auto; margin: 0 auto; object-fit: contain; border-radius: 14px; border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent); box-shadow: 0 30px 90px #000a; background: #101216; }
figcaption { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 0 4px; font-size: 12px; color: #cfc6b2; }
figcaption a { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--accent); }
figcaption a:hover { text-decoration: underline; }
.close { position: absolute; top: -14px; right: -14px; display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; color: #e5ddca; background: #171a20; border: 1px solid #ffffff1f; box-shadow: 0 6px 20px #0007; transition: transform 160ms, background 160ms; }
.close:hover { background: #22252c; transform: rotate(90deg); }
@media (max-width: 520px) { .close { top: 6px; right: 6px; } }
@keyframes zoom-in { from { opacity: 0; transform: scale(.94); } }
@keyframes fade { from { opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .lightbox[open], .lightbox::backdrop { animation: none; } .close { transition: none; } .close:hover { transform: none; } }
</style>
