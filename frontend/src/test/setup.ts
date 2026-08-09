import "@testing-library/jest-dom/vitest";

// Node 22+ ships its own global `localStorage`/`sessionStorage` (backed by
// --localstorage-file, unset here), which vitest's jsdom environment does not
// override since it isn't an own property of the jsdom window. That leaves
// Node's broken stub in place and breaks getItem/setItem. Point globalThis at
// the real jsdom-backed storage instead, reachable via globalThis.jsdom.
 
const realWindow = (globalThis as any).jsdom?.window;
if (realWindow) {
  for (const key of ["localStorage", "sessionStorage"] as const) {
    Object.defineProperty(globalThis, key, {
      value: realWindow[key],
      configurable: true,
      writable: true,
    });
  }
}

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// Recharts needs ResizeObserver in jsdom tests.
 
(globalThis as any).ResizeObserver = ResizeObserverMock;
