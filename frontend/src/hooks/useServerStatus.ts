import { useCallback, useEffect, useRef, useState } from "react";

import { checkHealth } from "../api";
import type { ServerState } from "../types";

const SLOW_AFTER_MS = 4000; // a healthy server answers well inside this
const GIVE_UP_AFTER_MS = 90000; // free hosting can take about a minute to wake

/**
 * Pings the API on load. Free hosting puts idle servers to sleep, so a first
 * request can hang for a long time: after a few seconds we report "waking"
 * (instead of looking frozen) and the ping itself warms the server up.
 */
export function useServerStatus() {
  const [state, setState] = useState<ServerState>("checking");
  const attempt = useRef(0);
  const abort = useRef<AbortController | null>(null);

  const check = useCallback(() => {
    abort.current?.abort();
    const id = ++attempt.current;
    const controller = new AbortController();
    abort.current = controller;
    setState("checking");

    const slowTimer = window.setTimeout(() => {
      if (attempt.current === id) setState((s) => (s === "checking" ? "waking" : s));
    }, SLOW_AFTER_MS);
    const giveUpTimer = window.setTimeout(() => controller.abort(), GIVE_UP_AFTER_MS);

    checkHealth(controller.signal).then((ok) => {
      window.clearTimeout(slowTimer);
      window.clearTimeout(giveUpTimer);
      if (attempt.current === id) setState(ok ? "online" : "offline");
    });
  }, []);

  useEffect(() => {
    check();
    return () => {
      attempt.current += 1; // invalidate anything still in flight
      abort.current?.abort();
    };
  }, [check]);

  const markOnline = useCallback(() => setState("online"), []);

  return { state, retry: check, markOnline };
}
