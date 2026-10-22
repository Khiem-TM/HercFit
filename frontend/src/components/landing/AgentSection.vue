<script setup lang="ts">
defineProps<{ selectedAgent: string }>();
defineEmits<{ select: [agent: string] }>();
const agents = [
  {
    name: "ARES",
    category: "KINETIC",
    description:
      "Tự động hóa giáo án kháng lực & tải cơ học tối ưu theo phản hồi cơ địa thời gian thực.",
    metrics: [
      ["MECHANICAL LOAD", "DYNAMIC Ψ"],
      ["ADAPTATION CYCLE", "< 140MS"],
    ],
  },
  {
    name: "DEMETER",
    category: "BIOENERGETIC",
    description:
      "Tự động hóa dinh dưỡng vi lượng, khả năng hấp thụ tế bào & điều hòa chu kỳ đồng hóa protein tối tân.",
    metrics: [
      ["CELLULAR BIOAVAIL", "99.2%"],
      ["GLYCEMIC STABILITY", "LOCKED"],
    ],
  },
  {
    name: "HERMES",
    category: "SYNAPSE",
    description:
      "Đồ thị tri thức hợp nhất 2.4 triệu công trình nghiên cứu y sinh với cơ sở dữ liệu sinh trắc cá nhân.",
    metrics: [
      ["CONNECTED NODES", "2.4M PUB"],
      ["CROSS-INFERENCE", "REAL-TIME"],
    ],
  },
  {
    name: "HYPNOS",
    category: "SOMATIC",
    description:
      "Tái thiết nhịp sinh học, phục hồi hệ thần kinh trung ương và tối đa hóa biên độ biến thiên tim (HRV).",
    metrics: [
      ["HRV AMPLITUDE", "+38.5 MS"],
      ["REM ARCHITECTURE", "SYNCHRONOUS"],
    ],
  },
];
</script>

<template>
  <section
    id="agents"
    class="px-margin-mobile md:px-margin lg:px-margin-desktop py-space-xl border-b border-outline-variant/30"
  >
    <div
      class="flex flex-col md:flex-row md:items-end justify-between mb-space-xl gap-space-md"
    >
      <div>
        <span class="eyebrow">// AUTONOMOUS DIVISION</span>
        <h2 class="section-heading">4 THẦN TÁC TỬ CHUYÊN BIỆT</h2>
      </div>
      <p class="font-body-sm text-body-sm text-on-surface-variant max-w-sm">
        Bốn cấu trúc trí tuệ nhân tạo phối hợp đồng bộ, biến cơ thể sinh học
        thành thực thể tối thượng thông qua dữ liệu thần học và sinh trắc chuẩn
        xác.
      </p>
    </div>
    <div
      class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-px bg-outline-variant/30 p-px"
    >
      <article
        v-for="(agent, index) in agents"
        :key="agent.name"
        class="agent-card bg-surface p-space-lg flex flex-col justify-between min-h-[320px] lg:min-h-[360px] hover:bg-surface-container-low transition-colors duration-200"
        :class="{ 'is-selected': selectedAgent === agent.name }"
      >
        <div class="flex flex-col gap-space-md">
          <div
            class="flex justify-between gap-2 font-label-telemetry text-label-telemetry text-outline"
          >
            <span>[AGENT 0{{ index + 1 }}]</span
            ><span class="text-primary tracking-widest">{{
              agent.category
            }}</span>
          </div>
          <h3
            class="font-headline-md text-headline-md text-primary tracking-wide"
          >
            {{ agent.name }}
          </h3>
          <p
            class="font-body-sm text-body-sm text-on-surface-variant leading-relaxed"
          >
            {{ agent.description }}
          </p>
        </div>
        <div
          class="space-y-space-sm pt-space-md mt-8 border-t border-outline-variant/20 font-label-code text-[10px] text-outline"
        >
          <div
            v-for="metric in agent.metrics"
            :key="metric[0]"
            class="flex justify-between gap-3"
          >
            <span>{{ metric[0] }}</span
            ><span class="text-primary">{{ metric[1] }}</span>
          </div>
          <a
            href="#access"
            class="inline-flex items-center gap-2 text-primary uppercase tracking-widest pt-2 hover:underline underline-offset-4"
            :aria-label="`Chọn giao thức ${agent.name}`"
            @click="$emit('select', agent.name)"
            >{{
              selectedAgent === agent.name
                ? "PROTOCOL SELECTED"
                : "ACTIVATE PROTOCOL"
            }}
            <span aria-hidden="true">[↗]</span></a
          >
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.is-selected {
  box-shadow: inset 0 0 0 1px #8f918c;
}
</style>
