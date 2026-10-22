<script setup lang="ts">
import { useAuth } from "@/composables/useAuth";

const { isAuthenticated, loginWithGoogle } = useAuth();

function handleStart(): void {
  if (isAuthenticated.value) {
    window.history.pushState({}, "", "/chat");
    window.dispatchEvent(new PopStateEvent("popstate"));
  } else {
    loginWithGoogle();
  }
}
</script>

<template>
  <section
    class="relative w-full min-h-[92vh] flex flex-col justify-between px-margin-mobile md:px-margin lg:px-margin-desktop py-space-xl border-b border-outline-variant/30 hero-section"
    id="archive"
  >
    <div
      class="w-full flex justify-between items-start font-label-telemetry text-label-telemetry uppercase tracking-widest text-outline"
    >
      <div class="flex items-center gap-space-sm">
        <span class="w-1.5 h-1.5 bg-primary rounded-none"></span>
        <span>PROTOCOL // OLYMPUS KINETIC</span>
      </div>
      <div class="text-right">
        <span>ARCHIVAL DISCIPLINE</span>
        <span class="text-on-surface-variant ml-2">// VER 4.09.AI</span>
      </div>
    </div>

    <div
      class="relative w-full my-auto flex flex-col items-center justify-center py-space-lg"
    >
      <div class="text-center z-10 max-w-5xl">
        <span
          class="font-label-code text-label-code tracking-[0.3em] uppercase text-on-surface-variant block mb-space-sm"
          >AUTONOMOUS MULTI-AGENT PHYSIOLOGY</span
        >
        <h1
          class="font-display-hero uppercase tracking-tighter text-primary font-normal leading-none drop-shadow-2xl hero-heading text-display-hero-mobile md:text-display-hero"
        >
          SCULPTING THE DIVINE ARCHITECTURE
        </h1>
      </div>

      <div
        class="relative w-full max-w-4xl h-[480px] md:h-[580px] flex items-center justify-center -my-space-md"
      >
        <svg
          class="absolute inset-0 w-full h-full pointer-events-none opacity-40"
          fill="none"
          viewbox="0 0 800 600"
        >
          <ellipse
            cx="400"
            cy="300"
            rx="360"
            ry="140"
            stroke="#8f918c"
            stroke-dasharray="3 3"
            stroke-width="0.75"
            transform="rotate(-18 400 300)"
          ></ellipse>
          <ellipse
            cx="400"
            cy="300"
            rx="340"
            ry="110"
            stroke="#8f918c"
            stroke-width="0.75"
            transform="rotate(22 400 300)"
          ></ellipse>
          <circle
            cx="400"
            cy="300"
            r="210"
            stroke="#454743"
            stroke-width="0.5"
          ></circle>
          <line
            stroke="#454743"
            stroke-dasharray="2 4"
            stroke-width="0.5"
            x1="400"
            x2="400"
            y1="50"
            y2="550"
          ></line>
          <line
            stroke="#454743"
            stroke-dasharray="2 4"
            stroke-width="0.5"
            x1="100"
            x2="700"
            y1="300"
            y2="300"
          ></line>

          <circle cx="210" cy="240" fill="#ffffff" r="3"></circle>
          <text
            fill="#8f918c"
            font-family="JetBrains Mono"
            font-size="9"
            letter-spacing="0.1em"
            x="220"
            y="244"
          >
            T12: KINETIC FLUX
          </text>
          <circle cx="590" cy="360" fill="#ffffff" r="3"></circle>
          <text
            fill="#8f918c"
            font-family="JetBrains Mono"
            font-size="9"
            letter-spacing="0.1em"
            x="600"
            y="364"
          >
            BIO: RESISTANCE 98.4%
          </text>
        </svg>

        <div
          class="relative z-10 h-full w-full max-w-md flex items-center justify-center"
        >
          <img
            alt="Classical Marble Sculpture Torso Back View"
            class="max-h-full w-auto object-contain filter grayscale contrast-125 brightness-95 select-none pointer-events-none drop-shadow-[0_25px_35px_rgba(0,0,0,0.9)]"
            decoding="async"
            fetchpriority="high"
            height="576"
            loading="eager"
            src="/images/hero-sculpture.png"
            width="384"
          />
        </div>

        <div
          class="absolute left-0 top-12 md:top-20 hidden md:block max-w-[240px] z-20"
        >
          <div
            class="border border-outline-variant/60 p-1 bg-surface-container-lowest/80 backdrop-blur-sm"
          >
            <div
              class="border border-outline-variant/40 p-space-md text-left flex flex-col gap-space-xs"
            >
              <span
                class="font-label-telemetry text-label-telemetry text-outline tracking-widest uppercase"
                >[EPIGRAM SEC.01]</span
              >
              <p
                class="font-quote-editorial text-[13px] leading-5 text-primary italic"
              >
                “Mỗi cơ thể là một bức tượng vĩnh cửu được đẽo gọt bởi trí tuệ
                nhân tạo.”
              </p>
              <div class="w-full h-px bg-outline-variant/40 my-1"></div>
              <span
                class="font-label-code text-[9px] uppercase tracking-wider text-on-surface-variant"
                >ETERNAL SCULPTURE // MMXXIV</span
              >
            </div>
          </div>
        </div>

        <div
          class="absolute right-0 bottom-10 hidden md:block max-w-[260px] z-20 text-right"
        >
          <div
            class="border border-outline-variant/60 p-1 bg-surface-container-lowest/80 backdrop-blur-sm"
          >
            <div
              class="border border-outline-variant/40 p-space-md flex flex-col gap-space-xs text-left"
            >
              <div
                class="flex justify-between items-center font-label-telemetry text-label-telemetry text-outline"
              >
                <span>VITAL HARMONICS</span>
                <span class="w-1.5 h-1.5 bg-primary"></span>
              </div>
              <div class="space-y-1 font-label-code text-label-code">
                <div class="flex justify-between text-on-surface">
                  <span class="text-outline">VO2 MAX REF</span>
                  <span>72.4 ML/KG</span>
                </div>
                <div class="flex justify-between text-on-surface">
                  <span class="text-outline">HYPERTROPHY COEFF</span>
                  <span>1.487 ψ</span>
                </div>
                <div class="flex justify-between text-on-surface">
                  <span class="text-outline">METABOLIC EQUILIB</span>
                  <span>OPTIMAL [0.94]</span>
                </div>
              </div>
              <div class="w-full h-1 bg-surface-variant mt-1 overflow-hidden">
                <div class="h-full bg-primary w-[88%]"></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div
        class="flex flex-col sm:flex-row items-center gap-space-md mt-space-lg z-20"
      >
        <button
          type="button"
          class="w-full sm:w-auto px-space-lg py-3.5 bg-primary text-background font-label-code text-label-code uppercase tracking-[0.2em] font-medium border border-primary hover:bg-background hover:text-primary transition-all duration-200 text-center"
          @click="handleStart"
        >
          [ KHỞI CHẠY HỆ THỐNG / ENTER SANCTUM ]
        </button>
        <a
          class="w-full sm:w-auto px-space-lg py-3.5 bg-transparent text-primary font-label-code text-label-code uppercase tracking-[0.2em] border border-outline-variant hover:border-primary transition-all duration-200 text-center flex items-center justify-center gap-space-xs"
          href="#agents"
        >
          <span>KHÁM PHÁ AGENTS</span>
          <span class="font-label-telemetry">→</span>
        </a>
      </div>
    </div>

    <div
      class="w-full grid grid-cols-2 md:grid-cols-4 gap-space-md pt-space-md border-t border-outline-variant/30 font-label-telemetry text-label-telemetry uppercase text-outline"
    >
      <div>COGNITIVE VECTOR // 01</div>
      <div>NEURAL EQUILIBRIUM // ACTIVE</div>
      <div class="text-left md:text-right">CELLULAR REFINEMENT // REALTIME</div>
      <div class="text-right">OLYMPUS CORE // 100%</div>
    </div>
  </section>
</template>
