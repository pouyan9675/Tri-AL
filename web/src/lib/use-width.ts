import { useLayoutEffect, useRef, useState } from "react";

/** A ref and the width of the element it's on, kept current with a ResizeObserver. */
export function useWidth<E extends HTMLElement>(initial = 0) {
  const ref = useRef<E>(null);
  const [width, setWidth] = useState(initial);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    setWidth(element.getBoundingClientRect().width || initial);
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [initial]);
  return [ref, width] as const;
}
