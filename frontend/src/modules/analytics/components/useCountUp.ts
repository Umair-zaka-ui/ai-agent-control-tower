import { useEffect, useRef, useState } from 'react'

/**
 * Animate a number from 0 → target on mount (SRS §KPI cards "Animate on load").
 * Respects prefers-reduced-motion by jumping straight to the target.
 */
export function useCountUp(target: number, durationMs = 700): number {
  const [value, setValue] = useState(0)
  const frame = useRef<number | undefined>(undefined)

  useEffect(() => {
    const reduce =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce || target === 0) {
      setValue(target)
      return
    }
    const start = performance.now()
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / durationMs)
      // easeOutCubic
      const eased = 1 - Math.pow(1 - progress, 3)
      setValue(target * eased)
      if (progress < 1) frame.current = requestAnimationFrame(tick)
      else setValue(target)
    }
    frame.current = requestAnimationFrame(tick)
    return () => {
      if (frame.current) cancelAnimationFrame(frame.current)
    }
  }, [target, durationMs])

  return value
}
