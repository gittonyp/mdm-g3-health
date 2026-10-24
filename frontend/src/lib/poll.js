import { onBeforeUnmount, onMounted } from "vue";

export function usePolling(fn, ms) {
  let timer = null;
  let inFlight = false;

  async function run() {
    if (typeof document !== "undefined" && document.hidden) return;
    if (inFlight) return;
    inFlight = true;
    try {
      await fn();
    } catch (error) {
      console.error(error);
    } finally {
      inFlight = false;
    }
  }

  function onVisibility() {
    if (!document.hidden) run();
  }

  onMounted(() => {
    run();
    timer = setInterval(run, ms);
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibility);
    }
  });

  onBeforeUnmount(() => {
    if (timer) clearInterval(timer);
    timer = null;
    if (typeof document !== "undefined") {
      document.removeEventListener("visibilitychange", onVisibility);
    }
  });

  return { run };
}
