import { shallowRef } from "vue";

export function useAccessRequest() {
  const email = shallowRef("");
  const saved = shallowRef(false);
  const error = shallowRef("");

  function submit(agent: string) {
    error.value = "";
    try {
      localStorage.setItem(
        "mythic.access-request",
        JSON.stringify({
          email: email.value.trim(),
          protocol: agent || "OLYMPUS",
          savedAt: new Date().toISOString(),
        }),
      );
      saved.value = true;
    } catch {
      saved.value = false;
      error.value =
        "Trình duyệt không cho phép lưu yêu cầu. Hãy bật bộ nhớ trang web và thử lại.";
    }
  }

  function reset() {
    saved.value = false;
    error.value = "";
  }
  function remove() {
    try {
      localStorage.removeItem("mythic.access-request");
      email.value = "";
      reset();
    } catch {
      error.value = "Không thể xoá dữ liệu trong trình duyệt này.";
    }
  }
  return { email, saved, error, submit, reset, remove };
}
