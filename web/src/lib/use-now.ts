import { useEffect, useState } from "react";

/** The current time, refreshed every `interval` ms, for relative times that keep up. */
export function useNow(interval = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), interval);
    return () => clearInterval(timer);
  }, [interval]);
  return now;
}
