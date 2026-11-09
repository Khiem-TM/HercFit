<script setup lang="ts">
import { computed, onMounted, onUnmounted, shallowRef, useTemplateRef, watch } from 'vue'
import {
  Color, DirectionalLight, HemisphereLight, Mesh, MeshStandardMaterial, PerspectiveCamera, Scene, SRGBColorSpace,
  Vector3, WebGLRenderer, type Object3D,
} from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { RotateCcw, RotateCw } from 'lucide-vue-next'
import { useTheme } from '@/composables/useTheme'
import { DURATION } from '@/motion'
import { bodyMorph, type BodyInputs, type BodyModel, type BodyMorph } from './bodyMorph'

/**
 * Mô hình cơ thể 3D (three.js) dựng từ public/models/body-{male,female}.glb (Anny/MakeHuman, xem
 * scripts/body-model). Chỉ xoay quanh trục đứng nên độ cao của đường gióng ngực/eo/hông trên màn hình không đổi.
 * Chỉ vẽ lại khi cần (xoay, đổi số đo, đổi giao diện); lỗi tải hay thiếu WebGL thì báo `failed` để dùng hình 2D.
 */
interface ModelMeta { height_cm: number; anchors: { chest: number; waist: number; hip: number } }

const props = defineProps<{ inputs: BodyInputs; label: string; height?: string; chest?: string; waist?: string; hip?: string }>()
const emit = defineEmits<{ failed: []; ready: [morph: BodyMorph] }>()

const FRAME_M = 2.15
const ROTATE_STEP = Math.PI / 6
const host = useTemplateRef<HTMLDivElement>('host')
const guides = shallowRef<{ top: number; ground: number; chest: number; waist: number; hip: number; width: number;
  height: number } | null>(null)
const ready = shallowRef(false)
const { resolved } = useTheme()

let renderer: WebGLRenderer | undefined
let camera: PerspectiveCamera | undefined
let controls: OrbitControls | undefined
let scene: Scene | undefined
let body: Mesh | undefined
const meta = shallowRef<Record<BodyModel, ModelMeta>>()
let loaded: BodyModel | undefined
let tween = 0
let observer: ResizeObserver | undefined
let disposed = false

const reduced = () => typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches
const skin = () => getComputedStyle(host.value ?? document.documentElement).getPropertyValue('--hf-body').trim() || '#C9CAD1'
const morph = computed(() => (meta.value ? bodyMorph(props.inputs, meta.value[props.inputs.sex === 'FEMALE' ? 'female' : 'male'].height_cm) : null))

function render() {
  if (renderer && scene && camera) renderer.render(scene, camera)
}

function measure() {
  const element = host.value
  if (!element || !camera || !renderer || !meta.value || !morph.value) return
  const { clientWidth: width, clientHeight: height } = element
  if (!width || !height) return
  renderer.setSize(width, height, false)
  camera.aspect = width / height
  camera.updateProjectionMatrix()
  const anchors = meta.value[morph.value.model]
  const tall = anchors.height_cm / 100 * morph.value.scale
  const screen = (y: number) => (1 - new Vector3(0, y, 0).project(camera!).y) / 2 * height
  guides.value = { width, height, top: screen(tall), ground: screen(0), chest: screen(tall * anchors.anchors.chest),
                   waist: screen(tall * anchors.anchors.waist), hip: screen(tall * anchors.anchors.hip) }
  render()
}

/** Chuyển morph và tỉ lệ tới số đo hiện tại (400 ms, tắt khi người dùng giảm chuyển động). */
function apply(target: BodyMorph) {
  const mesh = body
  if (!mesh?.morphTargetInfluences || !mesh.morphTargetDictionary) return
  const names = Object.keys(target.influences) as (keyof BodyMorph['influences'])[]
  const from = names.map(name => mesh.morphTargetInfluences![mesh.morphTargetDictionary![name]] ?? 0)
  const scaleFrom = mesh.scale.y
  const set = (t: number) => {
    names.forEach((name, index) => {
      const slot = mesh.morphTargetDictionary![name]
      if (slot !== undefined) mesh.morphTargetInfluences![slot] = from[index] + (target.influences[name] - from[index]) * t
    })
    mesh.scale.setScalar(scaleFrom + (target.scale - scaleFrom) * t)
  }
  cancelAnimationFrame(tween)
  if (reduced() || !ready.value) { set(1); measure(); return }
  const started = performance.now()
  const step = (now: number) => {
    const t = Math.min(1, (now - started) / (DURATION.slow * 1250))
    set(1 - (1 - t) ** 3)
    measure()
    if (t < 1) tween = requestAnimationFrame(step)
  }
  tween = requestAnimationFrame(step)
}

async function load(model: BodyModel) {
  const gltf = await new GLTFLoader().loadAsync(`/models/body-${model}.glb`)
  if (disposed || !scene) return
  let found: Mesh | undefined
  gltf.scene.traverse((node: Object3D) => { if (!found && (node as Mesh).isMesh) found = node as Mesh })
  if (!found) throw new Error('body mesh missing')
  if (body) {
    scene.remove(body)
    body.geometry.dispose()
  }
  const material = new MeshStandardMaterial({ color: new Color(skin()), roughness: 0.78, metalness: 0 })
  found.material = material
  found.removeFromParent()
  // Gốc toạ độ của mô hình là giữa hai bàn chân: phóng to/thu nhỏ quanh đó giữ chân trên mặt đất.
  found.position.set(0, 0, 0)
  scene.add(found)
  body = found
  loaded = model
}

async function setup() {
  const element = host.value
  if (!element) return
  const probe = document.createElement('canvas')
  if (!probe.getContext('webgl2') && !probe.getContext('webgl')) throw new Error('webgl unavailable')
  meta.value = await (await fetch('/models/body.json')).json() as Record<BodyModel, ModelMeta>
  if (disposed || !morph.value) return
  renderer = new WebGLRenderer({ antialias: true, alpha: true })
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1))
  renderer.outputColorSpace = SRGBColorSpace
  renderer.domElement.setAttribute('aria-hidden', 'true')
  element.prepend(renderer.domElement)
  scene = new Scene()
  scene.add(new HemisphereLight(0xffffff, 0x9a9aa4, 1.7))
  const key = new DirectionalLight(0xffffff, 2.1)
  key.position.set(-1.6, 2.6, 2.4)
  const rim = new DirectionalLight(0xffffff, 1.1)
  rim.position.set(1.8, 1.8, -2.2)
  scene.add(key, rim)
  camera = new PerspectiveCamera(26, 1, 0.1, 30)
  const distance = (FRAME_M / 2) / Math.tan((26 / 2) * Math.PI / 180) * 1.04
  camera.position.set(0, FRAME_M / 2, distance)
  controls = new OrbitControls(camera, renderer.domElement)
  controls.target.set(0, FRAME_M / 2, 0)
  controls.enableZoom = false
  controls.enablePan = false
  controls.minPolarAngle = controls.maxPolarAngle = Math.PI / 2
  controls.rotateSpeed = 0.7
  controls.update()
  controls.addEventListener('change', render)
  await load(morph.value.model)
  if (disposed) return
  apply(morph.value)
  observer = new ResizeObserver(measure)
  observer.observe(element)
  measure()
  ready.value = true
  emit('ready', morph.value)
}

function rotate(direction: 1 | -1) {
  if (!controls || !camera) return
  const offset = camera.position.clone().sub(controls.target)
  offset.applyAxisAngle(new Vector3(0, 1, 0), direction * ROTATE_STEP)
  camera.position.copy(controls.target).add(offset)
  controls.update()
}

watch(morph, async (next, previous) => {
  if (!next || !ready.value) return
  try {
    if (next.model !== loaded) await load(next.model)
    else if (previous && JSON.stringify(previous) === JSON.stringify(next)) return
    apply(next)
  } catch {
    emit('failed')
  }
})
watch(resolved, () => {
  const material = body?.material as MeshStandardMaterial | undefined
  if (!material) return
  requestAnimationFrame(() => { material.color.set(skin()); render() })  // chờ biến CSS của giao diện mới
})

onMounted(() => { setup().catch(() => { if (!disposed) emit('failed') }) })
onUnmounted(() => {
  disposed = true
  cancelAnimationFrame(tween)
  observer?.disconnect()
  controls?.dispose()
  if (body) {
    body.geometry.dispose()
    ;(body.material as MeshStandardMaterial).dispose()
  }
  renderer?.dispose()
  renderer?.domElement.remove()
})

</script>

<template>
  <div ref="host" class="body3d" :class="{ ready }" role="img" :aria-label="label">
    <svg v-if="guides && ready" class="overlay" :viewBox="`0 0 ${guides.width} ${guides.height}`" aria-hidden="true">
      <template v-if="height">
        <line x1="14" :y1="guides.top" x2="14" :y2="guides.ground" class="rule" />
        <line x1="10" :y1="guides.top" x2="18" :y2="guides.top" class="rule" />
        <line x1="10" :y1="guides.ground" x2="18" :y2="guides.ground" class="rule" />
        <text x="8" :y="(guides.top + guides.ground) / 2" :transform="`rotate(-90 8 ${(guides.top + guides.ground) / 2})`"
              text-anchor="middle" class="tag dim">{{ height }}</text>
      </template>
      <template v-if="chest">
        <line :x1="guides.width * 0.5" :y1="guides.chest" :x2="guides.width - 6" :y2="guides.chest" class="guide" />
        <text :x="guides.width - 6" :y="guides.chest - 6" text-anchor="end" class="tag">Ngực {{ chest }}</text>
      </template>
      <template v-if="waist">
        <line x1="24" :y1="guides.waist" :x2="guides.width * 0.5" :y2="guides.waist" class="guide" />
        <text x="24" :y="guides.waist - 6" class="tag">Eo {{ waist }}</text>
      </template>
      <template v-if="hip">
        <line :x1="guides.width * 0.5" :y1="guides.hip" :x2="guides.width - 6" :y2="guides.hip" class="guide" />
        <text :x="guides.width - 6" :y="guides.hip - 6" text-anchor="end" class="tag">Hông {{ hip }}</text>
      </template>
    </svg>
    <div v-if="ready" class="spin" role="group" aria-label="Xoay mô hình">
      <button type="button" class="hf-ib clear sm" aria-label="Xoay sang trái" @click="rotate(-1)"><RotateCcw :size="15" /></button>
      <button type="button" class="hf-ib clear sm" aria-label="Xoay sang phải" @click="rotate(1)"><RotateCw :size="15" /></button>
    </div>
  </div>
</template>

<style scoped>
.body3d {
  position: relative; width: 100%; height: 100%; opacity: 0; cursor: grab; touch-action: pan-y;
  transition: opacity var(--hf-dur-slow) var(--hf-ease-out);
}
.body3d.ready { opacity: 1; }
.body3d:active { cursor: grabbing; }
.body3d :deep(canvas) { display: block; width: 100%; height: 100%; }
.overlay { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; overflow: visible; }
.rule { stroke: var(--hf-ghost); stroke-width: 1; }
.guide { stroke: var(--hf-acc); stroke-width: 1; stroke-dasharray: 3 3; }
.tag { font-size: 11px; font-weight: 600; fill: var(--hf-ink); font-family: var(--hf-font); }
.tag.dim { fill: var(--hf-sub-2); }
.spin { position: absolute; right: 6px; bottom: 4px; display: flex; gap: 2px; }
</style>
