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
          alt="Tượng điêu khắc tự tạc mình từ cột đá, nền tinh vân"
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
          <span>KNOWLEDGE LAYER</span><span>FIG 02</span>
        </div>
        <div
          class="relative z-10 w-full border-t border-outline-variant/40 pt-space-sm mt-auto backdrop-blur-sm bg-background/50 px-space-sm py-1.5 flex justify-between items-center font-label-code text-[10px] text-on-surface-variant"
        >
          <span>POSTGRES → OUTBOX → NEO4J</span
          ><span class="text-primary font-medium">[GRAPH]</span>
        </div>
      </div>

      <div
        class="lg:col-span-7 flex flex-col justify-between h-full space-y-space-lg"
      >
        <div>
          <span
            class="font-label-telemetry text-label-telemetry text-outline uppercase tracking-widest block mb-space-xs"
            >// KNOWLEDGE GRAPH · CONTEXT GRAPH · RAG</span
          >
          <h2
            class="font-headline-lg text-primary uppercase font-bold tracking-tight mb-space-md text-headline-lg-mobile md:text-headline-lg"
          >
            TRI THỨC CÓ CẤU TRÚC, CÓ NGUỒN
          </h2>
          <p class="font-body-md text-body-md text-on-surface-variant max-w-xl">
            Nhật ký của bạn được chiếu thành đồ thị để trả lời câu hỏi có quan
            hệ (“tuần này tập nhiều hơn thì ngủ có kém đi không?”); kiến thức dinh
            dưỡng, vận động đến từ tài liệu đã duyệt và nguồn được phân hạng, kèm
            trích dẫn trong câu trả lời.
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
                  >KNOWLEDGE GRAPH</span
                >
              </div>
              <div
                class="flex items-center gap-space-lg text-on-surface-variant text-[11px] flex-wrap"
              >
                <span>POSTGRES OUTBOX → NEO4J</span>
                <span class="text-primary">[PROJECTION]</span>
              </div>
            </summary>
            <p
              class="pb-space-md pl-8 pr-3 font-body-sm text-body-sm text-on-surface-variant max-w-xl"
            >
              Mỗi bản ghi nhật ký phát một sự kiện outbox trong cùng giao dịch
              ghi; kg-worker chiếu sang Neo4j theo phiên bản, sự kiện chỉ được
              xác nhận sau khi đồ thị đã commit.
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
                  >CONTEXT GRAPH</span
                >
              </div>
              <div
                class="flex items-center gap-space-lg text-on-surface-variant text-[11px] flex-wrap"
              >
                <span>TEXT → CYPHER CHỈ ĐỌC</span>
                <span class="text-primary">[VALIDATED]</span>
              </div>
            </summary>
            <p
              class="pb-space-md pl-8 pr-3 font-body-sm text-body-sm text-on-surface-variant max-w-xl"
            >
              Mỗi câu hỏi rút một đồ thị con theo ý định: dùng mẫu truy vấn có
              sẵn hoặc để Context Agent viết Cypher. Chủ sở hữu và khoảng thời
              gian do code gán làm tham số; validator và policy chặn truy vấn
              ngoài phạm vi.
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
                  >HYBRID RAG</span
                >
              </div>
              <div
                class="flex items-center gap-space-lg text-on-surface-variant text-[11px] flex-wrap"
              >
                <span>PGVECTOR + FULL-TEXT · RRF</span>
                <span class="text-primary">[RERANKED]</span>
              </div>
            </summary>
            <p
              class="pb-space-md pl-8 pr-3 font-body-sm text-body-sm text-on-surface-variant max-w-xl"
            >
              Truy hồi lai trên tài liệu đã duyệt: tìm kiếm vector và toàn văn
              PostgreSQL gộp bằng Reciprocal Rank Fusion, xếp hạng lại, có ngưỡng
              liên quan. Dưới ngưỡng thì trả lời rõ là cơ sở tri thức chưa bao
              quát.
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
                  >NGUỒN PHÂN HẠNG</span
                >
              </div>
              <div
                class="flex items-center gap-space-lg text-on-surface-variant text-[11px] flex-wrap"
              >
                <span>SOURCE REGISTRY</span>
                <span class="text-primary">[CODE-OWNED]</span>
              </div>
            </summary>
            <p
              class="pb-space-md pl-8 pr-3 font-body-sm text-body-sm text-on-surface-variant max-w-xl"
            >
              Độ tin cậy của nguồn web đến từ sổ đăng ký nhà xuất bản do code
              quản lý (cơ quan y tế, cơ sở dữ liệu dinh dưỡng, hiệp hội chuyên
              môn), không từ nhãn của model. Nguồn không rõ chỉ là văn bản bổ
              trợ.
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
                >CÂU TRẢ LỜI CÓ TRÍCH NGUỒN</span
              >
              <span class="font-body-sm text-body-sm text-on-surface"
                >Câu hỏi tư vấn được tổng hợp từ dữ liệu của bạn và tài liệu
                đã truy hồi; mỗi ý dựa trên nguồn nào thì ghi nguồn đó.</span
              >
            </div>
          </div>
          <a
            class="font-label-code text-label-code text-primary uppercase shrink-0 hover:underline underline-offset-4"
            href="#protocols"
            >[XEM QUY TRÌNH]</a
          >
        </div>
      </div>
    </div>
  </section>
</template>
