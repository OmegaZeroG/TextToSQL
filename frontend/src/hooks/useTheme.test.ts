import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { loadTheme } from "../storage";
import { useTheme } from "./useTheme";

describe("useTheme", () => {
  it("starts from whatever theme the page was painted with", () => {
    document.documentElement.classList.add("dark");
    expect(renderHook(() => useTheme()).result.current.theme).toBe("dark");
  });

  it("starts light when the page has no dark class", () => {
    expect(renderHook(() => useTheme()).result.current.theme).toBe("light");
  });

  it("toggles, updates the page class, and remembers the choice", () => {
    const { result } = renderHook(() => useTheme());

    act(() => result.current.toggle());
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(loadTheme()).toBe("dark");

    act(() => result.current.toggle());
    expect(result.current.theme).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(loadTheme()).toBe("light");
  });

  it("fades all colours together while switching, then stops", () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggle());
    expect(document.documentElement.classList.contains("theme-switching")).toBe(true);
    act(() => {
      vi.advanceTimersByTime(400);
    });
    expect(document.documentElement.classList.contains("theme-switching")).toBe(false);
  });
});
