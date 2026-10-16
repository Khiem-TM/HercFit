import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { ChatMessage } from '@/types'

/**
 * Store quản lý hội thoại với LangGraph AI Agent.
 * TODO: Kết nối với agentApi (/invoke, /stream, /history).
 */
export const useChatStore = defineStore('chat', () => {
  const threadId = ref<string>('')
  const messages = ref<ChatMessage[]>([])
  const isStreaming = ref<boolean>(false)

  async function sendMessage(_message: string) {
    // TODO: Gửi tin nhắn và xử lý SSE stream từ Backend
  }

  return {
    threadId,
    messages,
    isStreaming,
    sendMessage,
  }
})
