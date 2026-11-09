import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { checkHealth } from "../api";
import { useServerStatus } from "./useServerStatus";

vi.mock("../api", () => ({ checkHealth: vi.fn() }));

/** A health check the test finishes by hand. */
function pendingHealthCheck() {
  let finish: (ok: boolean) => void = () => {};
  let signal: AbortSignal | undefined;
  vi.mocked(checkHealth).mockImplementation((s) => {
    signal = s;
    return new Promise<boolean>((resolve) => {
      finish = resolve;
    });
  });
  return { finish: (ok: boolean) => finish(ok), signal: () => signal };
}

beforeEach(() => {
  vi.mocked(checkHealth).mockReset();
});

describe("useServerStatus", () => {
  it("starts as checking, then reports online", async () => {
    const check = pendingHealthCheck();
    const { result } = renderHook(() => useServerStatus());
    expect(result.current.state).toBe("checking");
    await act(async () => check.finish(true));
    expect(result.current.state).toBe("online");
  });

  it("reports offline when the check fails", async () => {
    vi.mocked(checkHealth).mockResolvedValue(false);
    const { result } = renderHook(() => useServerStatus());
    await act(async () => {});
    expect(result.current.state).toBe("offline");
  });

  it("says the server is waking up if it is slow to answer, then reports online", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    const check = pendingHealthCheck();
    const { result } = renderHook(() => useServerStatus());

    act(() => {
      vi.advanceTimersByTime(3900);
    });
    expect(result.current.state).toBe("checking");
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(result.current.state).toBe("waking");

    await act(async () => check.finish(true));
    expect(result.current.state).toBe("online");
  });

  it("can be retried after going offline", async () => {
    vi.mocked(checkHealth).mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    const { result } = renderHook(() => useServerStatus());
    await act(async () => {});
    expect(result.current.state).toBe("offline");

    await act(async () => result.current.retry());
    expect(result.current.state).toBe("online");
    expect(checkHealth).toHaveBeenCalledTimes(2);
  });

  it("can be marked online by a successful request elsewhere", async () => {
    vi.mocked(checkHealth).mockResolvedValue(false);
    const { result } = renderHook(() => useServerStatus());
    await act(async () => {});
    act(() => result.current.markOnline());
    expect(result.current.state).toBe("online");
  });

  it("ignores a stale answer once a newer check has started", async () => {
    const first = pendingHealthCheck();
    const { result } = renderHook(() => useServerStatus());
    const secondCheck = pendingHealthCheck();
    act(() => result.current.retry());

    await act(async () => first.finish(false)); // the first (stale) check fails late
    expect(result.current.state).toBe("checking");

    await act(async () => secondCheck.finish(true));
    expect(result.current.state).toBe("online");
  });

  it("aborts an in-flight check on unmount", () => {
    const check = pendingHealthCheck();
    const { unmount } = renderHook(() => useServerStatus());
    expect(check.signal()?.aborted).toBe(false);
    unmount();
    expect(check.signal()?.aborted).toBe(true);
  });
});
