/**
 * Setup dla vitest (jsdom).
 *
 * jsdom nie ma dzialajacego PointerEvent - bez tego `clientX` w zdarzeniach
 * pointer nie dociera do Reacta i testy progress bara licza NaN.
 * MouseEvent ma to samo API, ktorego uzywamy (clientX, pointerId dokladamy
 * w testach), wiec podstawiamy go pod PointerEvent.
 */

if (typeof window !== 'undefined') {
  window.PointerEvent = MouseEvent as unknown as typeof PointerEvent
}

export {}
