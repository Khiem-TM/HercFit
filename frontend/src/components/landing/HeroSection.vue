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
        <span>HERCFIT // NHẬT KÝ DINH DƯỠNG &amp; TẬP LUYỆN</span>
      </div>
      <div class="text-right">
        <span>LANGGRAPH · FASTAPI</span>
        <span class="text-on-surface-variant ml-2">// VUE 3</span>
      </div>
    </div>

    <div
      class="relative w-full my-auto flex flex-col items-center justify-center py-space-lg"
    >
      <div class="text-center z-10 max-w-5xl hf-stagger">
        <span
          class="font-label-code text-label-code tracking-[0.3em] uppercase text-on-surface-variant block mb-space-md md:mb-space-lg"
          >TRỢ LÝ MULTI-AGENT TIẾNG VIỆT</span
        >
        <h1
          class="font-display-hero uppercase tracking-tighter text-primary font-bold leading-none drop-shadow-2xl hero-heading text-display-hero-mobile md:text-display-hero"
        >
          GHI BẰNG LỜI, LƯU KHI XÁC NHẬN
        </h1>
        <p class="mx-auto mt-space-md max-w-2xl font-body-lg text-body-lg text-on-surface-variant">
          Nhắn “trưa nay ăn một bát phở bò” hoặc “vừa chạy 5 km”: HercFit tra danh mục, tính năng lượng và chỉ ghi vào
          nhật ký sau khi bạn xem lại thẻ xác nhận. Câu hỏi tư vấn được trả lời từ dữ liệu của chính bạn và nguồn có
          trích dẫn.
        </p>
      </div>

      <div
        class="relative w-full max-w-4xl h-[480px] md:h-[580px] flex items-center justify-center mt-space-sm -mb-space-md md:-my-space-md"
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
            style="stroke: rgb(var(--c-outline))"
            stroke-dasharray="3 3"
            stroke-width="0.75"
            transform="rotate(-18 400 300)"
          ></ellipse>
          <ellipse
            cx="400"
            cy="300"
            rx="340"
            ry="110"
            style="stroke: rgb(var(--c-outline))"
            stroke-width="0.75"
            transform="rotate(22 400 300)"
          ></ellipse>
          <circle
            cx="400"
            cy="300"
            r="210"
            style="stroke: rgb(var(--c-outline-variant))"
            stroke-width="0.5"
          ></circle>
          <line
            style="stroke: rgb(var(--c-outline-variant))"
            stroke-dasharray="2 4"
            stroke-width="0.5"
            x1="400"
            x2="400"
            y1="50"
            y2="550"
          ></line>
          <line
            style="stroke: rgb(var(--c-outline-variant))"
            stroke-dasharray="2 4"
            stroke-width="0.5"
            x1="100"
            x2="700"
            y1="300"
            y2="300"
          ></line>

          <circle cx="210" cy="240" style="fill: rgb(var(--c-primary))" r="3"></circle>
          <text
            style="fill: rgb(var(--c-outline))"
            font-family="JetBrains Mono"
            font-size="9"
            letter-spacing="0.1em"
            x="220"
            y="244"
          >
            NODE: SUPERVISOR
          </text>
          <circle cx="590" cy="360" style="fill: rgb(var(--c-primary))" r="3"></circle>
          <text
            style="fill: rgb(var(--c-outline))"
            font-family="JetBrains Mono"
            font-size="9"
            letter-spacing="0.1em"
            x="600"
            y="364"
          >
            HITL: CONFIRM → WRITE
          </text>
        </svg>

        <div
          class="relative z-10 h-full w-full max-w-md flex items-center justify-center"
        >
          <img
            alt="Tượng cẩm thạch cổ điển, nhìn từ phía sau"
            class="max-h-full w-auto object-contain filter grayscale contrast-125 brightness-95 select-none pointer-events-none drop-shadow-[0_25px_35px_rgb(var(--c-shadow)/calc(0.9*var(--shadow-k)))]"
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
                >[NGUYÊN TẮC 01]</span
              >
              <p
                class="font-quote-editorial text-[13px] leading-5 text-primary italic"
              >
                “Agent đề xuất, bạn quyết định: không lệnh ghi nào chạy khi
                chưa được xác nhận.”
              </p>
              <div class="w-full h-px bg-outline-variant/40 my-1"></div>
              <span
                class="font-label-code text-[10px] uppercase tracking-wider text-on-surface-variant"
                >HUMAN-IN-THE-LOOP</span
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
                <span>STACK</span>
                <span class="w-1.5 h-1.5 bg-primary"></span>
              </div>
              <div class="space-y-1 font-label-code text-label-code">
                <div class="flex justify-between gap-3 text-on-surface">
                  <span class="text-outline">AGENT</span>
                  <span>LangGraph</span>
                </div>
                <div class="flex justify-between gap-3 text-on-surface">
                  <span class="text-outline">API</span>
                  <span>FastAPI · PostgreSQL</span>
                </div>
                <div class="flex justify-between gap-3 text-on-surface">
                  <span class="text-outline">GRAPH</span>
                  <span>Neo4j</span>
                </div>
                <div class="flex justify-between gap-3 text-on-surface">
                  <span class="text-outline">VECTOR</span>
                  <span>pgvector</span>
                </div>
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
          {{ isAuthenticated ? "[ VÀO TRỢ LÝ ]" : "[ BẮT ĐẦU VỚI GOOGLE ]" }}
        </button>
        <a
          class="w-full sm:w-auto px-space-lg py-3.5 bg-transparent text-primary font-label-code text-label-code uppercase tracking-[0.2em] border border-outline-variant hover:border-primary transition-all duration-200 text-center flex items-center justify-center gap-space-xs"
          href="#agents"
        >
          <span>XEM KIẾN TRÚC</span>
          <span class="font-label-telemetry">→</span>
        </a>
      </div>
    </div>

    <div
      class="w-full grid grid-cols-2 md:grid-cols-4 gap-space-md pt-space-md border-t border-outline-variant/30 font-label-telemetry text-label-telemetry uppercase text-outline"
    >
      <div>HITL // MỌI LỆNH GHI</div>
      <div>IDEMPOTENT // CÓ PHIÊN BẢN</div>
      <div class="text-left md:text-right">RAG // CÓ TRÍCH NGUỒN</div>
      <div class="text-right">TRACING // LANGFUSE</div>
    </div>
  </section>
</template>
