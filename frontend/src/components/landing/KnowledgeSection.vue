<script setup lang="ts">
import { Network } from "lucide-vue-next";
</script>

<template>
  <section
    class="w-full px-margin-mobile md:px-margin lg:px-margin-desktop py-space-xl border-b border-outline-variant/30"
    id="knowledge"
  >
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-space-xl items-center">
      <div
        class="lg:col-span-5 relative flex flex-col justify-between overflow-hidden border border-outline-variant/30 bg-surface-container-lowest min-h-[520px] p-space-md group"
      >
        <img
          alt="Sculptor Carving Himself from Corinthian Column - Celestial Nebula"
          class="absolute inset-0 w-full h-full object-cover object-center filter contrast-125 brightness-95 select-none pointer-events-none transition-transform duration-700 group-hover:scale-105"
          decoding="async"
          height="1024"
          loading="lazy"
          src="/images/knowledge-sculpture.jpg"
          width="768"
        />
        <div
          class="absolute inset-0 bg-gradient-to-b from-background/80 via-transparent to-background/90 pointer-events-none"
        ></div>
        <div
          class="relative z-10 w-full flex justify-between font-label-telemetry text-label-telemetry text-outline backdrop-blur-sm bg-background/40 px-space-sm py-1 border border-outline-variant/30"
        >
          <span>SPECIMEN // CHISEL OF SELF</span><span>FIG 08.B</span>
        </div>
        <div
          class="relative z-10 w-full border-t border-outline-variant/40 pt-space-sm mt-auto backdrop-blur-sm bg-background/50 px-space-sm py-1.5 flex justify-between items-center font-label-code text-[10px] text-on-surface-variant"
        >
          <span>CORINTHIAN ORDER RECONSTRUCTION</span
          ><span class="text-primary font-medium">[AUTONOMY]</span>
        </div>
      </div>

      <div
        class="lg:col-span-7 flex flex-col justify-between h-full space-y-space-lg"
      >
        <div>
          <span
            class="font-label-telemetry text-label-telemetry text-outline uppercase tracking-widest block mb-space-xs"
            >// OBSERVATORY KNOWLEDGE MAPPING</span
          >
          <h2
            class="font-headline-lg text-primary uppercase font-normal tracking-tight mb-space-md text-headline-lg-mobile md:text-headline-lg"
          >
            SINH THÁI ĐỒ THỊ ĐA CHIỀU
          </h2>
          <p class="font-body-md text-body-md text-on-surface-variant max-w-xl">
            Tương tự như cấu trúc các chòm sao trên bầu trời đêm của đài quan
            sát, mỗi điểm dữ liệu sinh học được ánh xạ vào một mạng lưới vô hạn,
            xóa bỏ phương thức phán đoán chủ quan.
          </p>
        </div>

        <div
          class="w-full flex flex-col border-t border-outline-variant/40 divide-y divide-outline-variant/30 font-label-code text-label-code"
        >
          <details class="knowledge-row group">
            <summary
              class="py-space-md flex flex-col xl:flex-row xl:items-center justify-between gap-space-sm cursor-pointer hover:bg-surface-container/40 transition-colors"
            >
              <div class="flex items-center gap-space-md">
                <span class="text-outline font-label-telemetry">[01]</span>
                <span
                  class="text-primary uppercase tracking-wider font-headline-sm text-headline-sm registry-title"
                  >HORMONAL PULSATILITY</span
                >
              </div>
              <div
                class="flex items-center gap-space-lg text-on-surface-variant text-[11px] flex-wrap"
              >
                <span>CORTISOL / TESTOSTERONE RATIO</span>
                <span class="text-primary">[SYNCHRONIZED]</span>
              </div>
            </summary>
            <p
              class="pb-space-md pl-8 pr-3 font-body-sm text-body-sm text-on-surface-variant max-w-xl"
            >
              Theo dõi nhịp biến đổi của dữ liệu nội tiết để nhìn thấy xu hướng
              trong cùng một bối cảnh sinh học.
            </p>
          </details>

          <details class="knowledge-row group">
            <summary
              class="py-space-md flex flex-col xl:flex-row xl:items-center justify-between gap-space-sm cursor-pointer hover:bg-surface-container/40 transition-colors"
            >
              <div class="flex items-center gap-space-md">
                <span class="text-outline font-label-telemetry">[02]</span>
                <span
                  class="text-primary uppercase tracking-wider font-headline-sm text-headline-sm registry-title"
                  >MYOFIBRILLAR HYPERTROPHY</span
                >
              </div>
              <div
                class="flex items-center gap-space-lg text-on-surface-variant text-[11px] flex-wrap"
              >
                <span>TENSION-TIME INTEGRATION</span>
                <span class="text-primary">[OPTIMIZED]</span>
              </div>
            </summary>
            <p
              class="pb-space-md pl-8 pr-3 font-body-sm text-body-sm text-on-surface-variant max-w-xl"
            >
              Kết nối tải trọng, số lần lặp và thời gian chịu lực thành lịch sử
              vận động có thể so sánh.
            </p>
          </details>

          <details class="knowledge-row group">
            <summary
              class="py-space-md flex flex-col xl:flex-row xl:items-center justify-between gap-space-sm cursor-pointer hover:bg-surface-container/40 transition-colors"
            >
              <div class="flex items-center gap-space-md">
                <span class="text-outline font-label-telemetry">[03]</span>
                <span
                  class="text-primary uppercase tracking-wider font-headline-sm text-headline-sm registry-title"
                  >MITOCHONDRIAL RESCUE</span
                >
              </div>
              <div
                class="flex items-center gap-space-lg text-on-surface-variant text-[11px] flex-wrap"
              >
                <span>ATP RESYNTHESIS EFFICIENCY</span>
                <span class="text-primary">[ACTIVE]</span>
              </div>
            </summary>
            <p
              class="pb-space-md pl-8 pr-3 font-body-sm text-body-sm text-on-surface-variant max-w-xl"
            >
              Đặt dữ liệu vận động cạnh thông tin dinh dưỡng và phục hồi để khám
              phá mối liên hệ.
            </p>
          </details>

          <details class="knowledge-row group">
            <summary
              class="py-space-md flex flex-col xl:flex-row xl:items-center justify-between gap-space-sm cursor-pointer hover:bg-surface-container/40 transition-colors"
            >
              <div class="flex items-center gap-space-md">
                <span class="text-outline font-label-telemetry">[04]</span>
                <span
                  class="text-primary uppercase tracking-wider font-headline-sm text-headline-sm registry-title"
                  >CIRCADIAN ALIGNMENT</span
                >
              </div>
              <div
                class="flex items-center gap-space-lg text-on-surface-variant text-[11px] flex-wrap"
              >
                <span>MELATONIN KINETICS</span>
                <span class="text-primary">[LOCKED]</span>
              </div>
            </summary>
            <p
              class="pb-space-md pl-8 pr-3 font-body-sm text-body-sm text-on-surface-variant max-w-xl"
            >
              Quan sát thời gian ngủ, hoạt động và nghỉ ngơi theo chu kỳ ngày
              đêm của bạn.
            </p>
          </details>
        </div>

        <div
          class="border border-outline-variant/40 p-space-md bg-surface-container-lowest flex items-center justify-between"
        >
          <div class="flex items-center gap-space-md">
            <Network
              :size="20"
              aria-hidden="true"
              class="text-outline shrink-0"
            ></Network>
            <div class="flex flex-col">
              <span
                class="font-label-telemetry text-label-telemetry text-outline uppercase tracking-wider"
                >KNOWLEDGE MATRIX DENSITY</span
              >
              <span class="font-body-sm text-body-sm text-on-surface"
                >2,419,820 Peer-reviewed studies indexed &amp;
                operationalized</span
              >
            </div>
          </div>
          <a
            class="font-label-code text-label-code text-primary uppercase shrink-0 hover:underline underline-offset-4"
            href="#protocols"
            >[EXPLORE ENGINE]</a
          >
        </div>
      </div>
    </div>
  </section>
</template>
