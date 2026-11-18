<template>
  <section
    class="w-full px-margin-mobile md:px-margin lg:px-margin-desktop py-space-xl border-b border-outline-variant/30"
    id="protocols"
  >
    <div
      class="w-full flex flex-col items-center text-center max-w-2xl mx-auto mb-space-xl"
    >
      <span
        class="font-label-telemetry text-label-telemetry text-outline uppercase tracking-widest block mb-space-xs"
        >// MỘT LƯỢT CHAT</span
      >
      <h2
        class="font-headline-lg text-primary uppercase font-bold tracking-tight text-headline-lg-mobile md:text-headline-lg"
      >
        TỪ CÂU NÓI ĐẾN BẢN GHI
      </h2>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-4 gap-space-lg relative">
      <div
        class="relative flex flex-col p-space-md border border-outline-variant/40 bg-surface-container-lowest"
      >
        <div
          class="font-label-telemetry text-label-telemetry text-outline mb-space-sm flex justify-between"
        >
          <span>BƯỚC 01</span>
          <span>ROUTE</span>
        </div>
        <h4
          class="font-headline-sm text-headline-sm text-primary uppercase mb-space-xs"
        >
          ĐỊNH TUYẾN
        </h4>
        <p
          class="font-body-sm text-body-sm text-on-surface-variant leading-relaxed"
        >
          Câu gõ hoặc nói đi qua luật của code trước: câu ghi đơn giản khớp danh
          mục đi đường nhanh, câu nhiều việc được tách cho các agent.
        </p>
        <div
          class="mt-space-lg pt-space-sm border-t border-outline-variant/20 font-label-telemetry text-[10px] text-outline"
        >
          INPUT // CHAT · GIỌNG NÓI
        </div>
      </div>

      <div
        class="relative flex flex-col p-space-md border border-outline-variant/40 bg-surface-container-lowest"
      >
        <div
          class="font-label-telemetry text-label-telemetry text-outline mb-space-sm flex justify-between"
        >
          <span>BƯỚC 02</span>
          <span>TOOLS</span>
        </div>
        <h4
          class="font-headline-sm text-headline-sm text-primary uppercase mb-space-xs"
        >
          AGENT XỬ LÝ
        </h4>
        <p
          class="font-body-sm text-body-sm text-on-surface-variant leading-relaxed"
        >
          Agent chuyên trách chỉ gọi tool của miền mình. Thiếu thông tin thì hỏi
          lại bằng thẻ có lựa chọn thay vì tự đoán.
        </p>
        <div
          class="mt-space-lg pt-space-sm border-t border-outline-variant/20 font-label-telemetry text-[10px] text-outline"
        >
          TOOLS // THEO MIỀN
        </div>
      </div>

      <div
        class="relative flex flex-col p-space-md border border-outline-variant/40 bg-surface-container-lowest"
      >
        <div
          class="font-label-telemetry text-label-telemetry text-outline mb-space-sm flex justify-between"
        >
          <span>BƯỚC 03</span>
          <span>HITL</span>
        </div>
        <h4
          class="font-headline-sm text-headline-sm text-primary uppercase mb-space-xs"
        >
          XÁC NHẬN
        </h4>
        <p
          class="font-body-sm text-body-sm text-on-surface-variant leading-relaxed"
        >
          Lệnh ghi dừng ở thẻ xác nhận có phiên bản và hạn dùng: xem lại, sửa,
          duyệt hoặc từ chối, bằng nút hoặc bằng câu nói.
        </p>
        <div
          class="mt-space-lg pt-space-sm border-t border-outline-variant/20 font-label-telemetry text-[10px] text-outline"
        >
          HUMAN-IN-THE-LOOP
        </div>
      </div>

      <div
        class="relative flex flex-col p-space-md border border-primary/40 bg-surface-container-lowest"
      >
        <div
          class="font-label-telemetry text-label-telemetry text-primary mb-space-sm flex justify-between"
        >
          <span>BƯỚC 04</span>
          <span>COMMIT</span>
        </div>
        <h4
          class="font-headline-sm text-headline-sm text-primary uppercase mb-space-xs"
        >
          GHI &amp; QUAN SÁT
        </h4>
        <p
          class="font-body-sm text-body-sm text-on-surface-variant leading-relaxed"
        >
          Ghi idempotent kèm khoá phiên bản, đồ thị tri thức cập nhật qua
          outbox. Mỗi lượt có trace và kết cục để đo lường, đánh giá.
        </p>
        <div
          class="mt-space-lg pt-space-sm border-t border-primary/20 font-label-telemetry text-[10px] text-primary"
        >
          IDEMPOTENCY · LANGFUSE
        </div>
      </div>
    </div>
  </section>
</template>
