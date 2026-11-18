// Theme trước lần vẽ đầu (src/composables/useTheme.ts đồng bộ tiếp sau đó). Là tệp riêng cùng origin, không phải script
// inline, để CSP `script-src 'self'` của Caddyfile không chặn nó.
(function () {
  try {
    var mode = localStorage.getItem("hercfit:theme");
    // Chưa chọn: ứng dụng (/chat) sáng theo thiết kế, trang giới thiệu tối (useTheme.ts).
    if (mode !== "light" && mode !== "dark" && mode !== "system") mode = location.pathname.indexOf("/chat") === 0 ? "light" : "dark";
    var light = mode === "light" || (mode === "system" && matchMedia("(prefers-color-scheme: light)").matches);
    document.documentElement.classList.toggle("light", light);
    document.documentElement.classList.toggle("dark", !light);
  } catch (e) {}
})();
