import { useEffect, useState } from "react";

/** Milliseconds since `running` last became true; 0 while it is false. */
export function useElapsed(running: boolean, intervalMs = 250): number {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!running) {
      setElapsed(0);
      return;
    }
    const start = performance.now();
    const timer = window.setInterval(() => setElapsed(performance.now() - start), intervalMs);
    return () => window.clearInterval(timer);
  }, [running, intervalMs]);

  return elapsed;
}
