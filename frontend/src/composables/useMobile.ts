import { ref } from 'vue'

/**
 * Bố cục điện thoại (≤ 760px, cùng mốc với @media trong CSS) và bàn phím ảo. Trạng thái dùng chung ở mức module.
 * Bàn phím ảo không có sự kiện riêng: nhận ra khi vùng nhìn thấy (visualViewport) thấp hẳn so với lúc cao nhất.
 */
const query = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia('(max-width: 760px)') : null
const isMobile = ref(query?.matches ?? false)
query?.addEventListener('change', event => { isMobile.value = event.matches })

const keyboardOpen = ref(false)
/** Chiều cao vùng nhìn thấy (px); khi bàn phím mở, khung ứng dụng co theo để ô soạn tin nằm ngay trên bàn phím. */
const viewportHeight = ref(0)
const viewport = typeof window !== 'undefined' ? window.visualViewport : null
if (viewport) {
  let width = viewport.width
  let tallest = 0
  const measure = () => {
    // Nhân scale để thao tác phóng to bằng hai ngón không bị nhận nhầm thành bàn phím.
    const height = viewport.height * viewport.scale
    if (viewport.width !== width) { width = viewport.width; tallest = 0 }  // xoay máy: đo lại từ đầu
    tallest = Math.max(tallest, height)
    viewportHeight.value = Math.round(height)
    keyboardOpen.value = tallest - height > 150
  }
  measure()
  viewport.addEventListener('resize', measure)
}

export function useMobile() {
  return { isMobile, keyboardOpen, viewportHeight }
}
