import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { cn } from "../lib/cn";
import { GUIDE_STEPS, type GuideStep, type Placement } from "../lib/guideSteps";
import Button from "./ui/Button";
import Icon from "./ui/Icon";

interface Props {
  open: boolean;
  onClose: () => void;
  steps?: GuideStep[];
}

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

interface View {
  spot: Box | null;
  card: { top: number; left: number; width: number };
}

const EXIT_MS = 200;
// A dark scrim in both themes (the foreground token is light in dark mode, which would wash the page out).
const SCRIM = "oklch(12% 0.012 165 / 0.62)";
const SPOT_PAD = 8; // breathing room around the highlighted element
const GAP = 14; // between the highlight and the card
const MARGIN = 16; // minimum distance from the screen edge
const CARD_WIDTH = 340;
const PHONE = 640; // below this the card docks to the bottom as a sheet
const HEADER = 72; // sticky header plus a little air: keep targets below it

const sameBox = (a: Box | null, b: Box | null) =>
  a === b || (!!a && !!b && a.top === b.top && a.left === b.left && a.width === b.width && a.height === b.height);

function findTarget(step: GuideStep): DOMRect | null {
  if (!step.target) return null;
  const el = document.querySelector(`[data-guide="${step.target}"]`);
  if (!el) return null;
  const rect = el.getBoundingClientRect();
  return rect.width > 0 || rect.height > 0 ? rect : null;
}

/** Scrolls the highlighted element into the part of the screen the card isn't covering. */
function bringIntoView(step: GuideStep) {
  const rect = findTarget(step);
  if (!rect) return;
  const phone = window.innerWidth < PHONE;
  const bottomLimit = phone ? window.innerHeight - 240 : window.innerHeight - MARGIN;
  if (rect.top >= HEADER && rect.bottom <= bottomLimit) return;

  const roomy = bottomLimit - HEADER;
  const absoluteTop = rect.top + window.scrollY;
  const top = rect.height > roomy ? absoluteTop - HEADER : absoluteTop - HEADER - (roomy - rect.height) / 2;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({ top: Math.max(0, top), behavior: reduced ? "auto" : "smooth" });
}

function placeCard(rect: DOMRect | null, cardHeight: number, prefer: Placement | undefined) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  if (vw < PHONE) {
    return { top: vh - cardHeight - MARGIN, left: MARGIN, width: vw - MARGIN * 2 };
  }

  const width = Math.min(CARD_WIDTH, vw - MARGIN * 2);
  const clampX = (x: number) => Math.min(Math.max(x, MARGIN), vw - width - MARGIN);
  const clampY = (y: number) => Math.min(Math.max(y, MARGIN), vh - cardHeight - MARGIN);

  if (!rect) return { top: clampY((vh - cardHeight) / 2), left: clampX((vw - width) / 2), width };

  const options: Record<Placement, { top: number; left: number; fits: boolean }> = {
    bottom: {
      top: rect.bottom + SPOT_PAD + GAP,
      left: clampX(rect.left),
      fits: rect.bottom + SPOT_PAD + GAP + cardHeight <= vh - MARGIN,
    },
    top: {
      top: rect.top - SPOT_PAD - GAP - cardHeight,
      left: clampX(rect.left),
      fits: rect.top - SPOT_PAD - GAP - cardHeight >= MARGIN,
    },
    right: {
      top: clampY(rect.top),
      left: rect.right + SPOT_PAD + GAP,
      fits: rect.right + SPOT_PAD + GAP + width <= vw - MARGIN,
    },
    left: {
      top: clampY(rect.top),
      left: rect.left - SPOT_PAD - GAP - width,
      fits: rect.left - SPOT_PAD - GAP - width >= MARGIN,
    },
  };

  const order: Placement[] = [prefer ?? "bottom", "bottom", "top", "right", "left"];
  const choice = order.find((placement) => options[placement].fits);
  if (choice) return { top: options[choice].top, left: options[choice].left, width };

  // Nothing fits (a target taller than the screen): float in the corner.
  return { top: vh - cardHeight - MARGIN, left: vw - width - MARGIN, width };
}

export default function GuideTour({ open, onClose, steps = GUIDE_STEPS }: Props) {
  const [mounted, setMounted] = useState(open);
  const [leaving, setLeaving] = useState(false);
  const [index, setIndex] = useState(0);
  const [view, setView] = useState<View | null>(null);
  // Positions only glide between steps; the first placement on open must not slide in from a corner.
  const [settled, setSettled] = useState(false);

  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const bodyId = useId();

  const step = steps[Math.min(index, steps.length - 1)];
  const last = index >= steps.length - 1;

  // Mount on open, fade out before unmounting on close.
  useEffect(() => {
    if (open) {
      setMounted(true);
      setLeaving(false);
      setIndex(0);
      return;
    }
    setLeaving(true);
    const timer = window.setTimeout(() => {
      setMounted(false);
      setLeaving(false);
    }, EXIT_MS);
    returnFocus.current?.focus({ preventScroll: true });
    returnFocus.current = null;
    return () => window.clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!mounted) {
      setSettled(false);
      setView(null);
      return;
    }
    if (view === null) return;
    const frame = requestAnimationFrame(() => setSettled(true));
    return () => cancelAnimationFrame(frame);
  }, [mounted, view === null]); // eslint-disable-line react-hooks/exhaustive-deps

  const measure = useCallback(() => {
    const rect = findTarget(step);
    const spot: Box | null = rect
      ? {
          top: rect.top - SPOT_PAD,
          left: rect.left - SPOT_PAD,
          width: rect.width + SPOT_PAD * 2,
          height: rect.height + SPOT_PAD * 2,
        }
      : null;
    const card = placeCard(rect, cardRef.current?.offsetHeight || 190, step.prefer);
    setView((previous) =>
      previous &&
      sameBox(previous.spot, spot) &&
      previous.card.top === card.top &&
      previous.card.left === card.left &&
      previous.card.width === card.width
        ? previous
        : { spot, card },
    );
  }, [step]);

  // New step: bring its target into view, measure, and hand focus to the primary button.
  useLayoutEffect(() => {
    if (!mounted || !open) return;
    const active = document.activeElement;
    if (!returnFocus.current && active instanceof HTMLElement && !cardRef.current?.contains(active)) {
      returnFocus.current = active; // where to send focus back to when the tour closes
    }
    bringIntoView(step);
    measure();
    nextRef.current?.focus({ preventScroll: true });
  }, [mounted, open, step, measure]);

  // Follow the target while the page scrolls, resizes or reflows.
  useEffect(() => {
    if (!mounted || !open) return;
    let frame = 0;
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    window.addEventListener("resize", schedule);
    window.addEventListener("scroll", schedule, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", schedule);
      window.removeEventListener("scroll", schedule, true);
    };
  }, [mounted, open, measure]);

  const next = useCallback(() => {
    if (last) onClose();
    else setIndex((i) => i + 1);
  }, [last, onClose]);
  const back = useCallback(() => setIndex((i) => Math.max(0, i - 1)), []);

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      } else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        onClose(); // the submit shortcut ends the tour; the question card handles the submit itself
      } else if (event.key === "ArrowRight") {
        next();
      } else if (event.key === "ArrowLeft") {
        back();
      } else if (event.key === "Tab" && cardRef.current) {
        const focusable = Array.from(cardRef.current.querySelectorAll<HTMLElement>("button:not([disabled])"));
        if (focusable.length === 0) return;
        const first = focusable[0];
        const lastEl = focusable[focusable.length - 1];
        const active = document.activeElement;
        if (!cardRef.current.contains(active)) {
          event.preventDefault();
          first.focus();
        } else if (event.shiftKey && active === first) {
          event.preventDefault();
          lastEl.focus();
        } else if (!event.shiftKey && active === lastEl) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, next, back, onClose]);

  if (!mounted) return null;

  const spot = view?.spot ?? null;

  return createPortal(
    <div className={cn("fixed inset-0 z-[70] transition-opacity duration-200", leaving ? "opacity-0" : "animate-fade-in")}>
      {/* Swallows clicks so the page can't be changed mid-tour. */}
      <div className="absolute inset-0" aria-hidden="true" />

      {/* Whole-screen dim, used when a step has nothing to point at. */}
      <div
        aria-hidden="true"
        className={cn(
          "absolute inset-0 transition-opacity duration-300",
          spot ? "opacity-0" : "opacity-100",
        )}
        style={{ background: SCRIM }}
      />

      {/* The highlight: a hole in the dimmed page that glides from step to step. */}
      {spot && (
        <div
          aria-hidden="true"
          className={cn(
            "pointer-events-none absolute rounded-xl ring-2 ring-primary/80",
            settled && "transition-[top,left,width,height] duration-300 ease-out",
          )}
          style={{
            top: spot.top,
            left: spot.left,
            width: spot.width,
            height: spot.height,
            boxShadow: `0 0 0 9999px ${SCRIM}`,
          }}
        />
      )}

      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        className={cn(
          "absolute rounded-xl border border-border bg-card shadow-pop",
          settled && "transition-[top,left,width] duration-300 ease-out",
          !view && "opacity-0",
        )}
        style={view ? view.card : { top: 0, left: 0, width: CARD_WIDTH }}
      >
        <div key={index} className="animate-tour-in p-4">
          <div className="mb-2 flex items-center justify-between">
            <p className="font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-primary">
              Step {index + 1} of {steps.length}
            </p>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close guide"
              className="-mr-1.5 -mt-1.5 grid size-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <Icon name="x" />
            </button>
          </div>

          <h2 id={titleId} className="text-[15px] font-semibold tracking-tight">
            {step.title}
          </h2>
          <p id={bodyId} className="mt-1 text-sm leading-relaxed text-muted-foreground">
            {step.body}
          </p>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-3">
          <div className="flex items-center gap-1.5" aria-hidden="true">
            {steps.map((_, i) => (
              <span
                key={i}
                className={cn(
                  "h-1.5 rounded-full transition-all duration-300",
                  i === index ? "w-5 bg-primary" : i < index ? "w-1.5 bg-primary/40" : "w-1.5 bg-border",
                )}
              />
            ))}
          </div>
          <div className="flex items-center gap-1.5">
            {index > 0 && (
              <Button variant="ghost" size="sm" onClick={back}>
                <Icon name="arrowLeft" />
                Back
              </Button>
            )}
            <Button ref={nextRef} variant="primary" size="sm" onClick={next}>
              {last ? "Done" : "Next"}
              {!last && <Icon name="arrowRight" />}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
