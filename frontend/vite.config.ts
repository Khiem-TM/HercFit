import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    rollupOptions: {
      output: {
        // Bộ vẽ graph rất lớn và chỉ cần khi bảng tri thức được mở.
        manualChunks: (id) => (id.includes("node_modules/cytoscape") ? "cytoscape" : undefined),
      },
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api/v1/chat": {
        target: "http://localhost:8081",
        changeOrigin: true,
      },
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        // WebSocket thông báo (/api/v2/notifications/stream).
        ws: true,
      },
    },
  },
});
