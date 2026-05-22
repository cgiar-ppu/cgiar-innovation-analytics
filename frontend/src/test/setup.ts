import '@testing-library/jest-dom'

// ---------------------------------------------------------------------------
// localStorage shim
// jsdom sometimes does not provide a functional localStorage (e.g. when run
// in certain vitest configurations). We install a Map-backed shim so that
// any module that calls localStorage.getItem/setItem at load time doesn't
// throw.
// ---------------------------------------------------------------------------
const localStorageStore = new Map<string, string>()

const localStorageShim: Storage = {
  get length() { return localStorageStore.size },
  key(index: number): string | null {
    return Array.from(localStorageStore.keys())[index] ?? null
  },
  getItem(key: string): string | null {
    return localStorageStore.get(key) ?? null
  },
  setItem(key: string, value: string): void {
    localStorageStore.set(key, value)
  },
  removeItem(key: string): void {
    localStorageStore.delete(key)
  },
  clear(): void {
    localStorageStore.clear()
  },
}

Object.defineProperty(globalThis, 'localStorage', {
  value: localStorageShim,
  writable: true,
  configurable: true,
})

// ---------------------------------------------------------------------------
// window.matchMedia shim
// jsdom does not implement matchMedia. Provide a minimal stub so that stores
// (e.g. ui.ts) that call window.matchMedia at module load time don't throw.
// ---------------------------------------------------------------------------
Object.defineProperty(globalThis, 'matchMedia', {
  writable: true,
  configurable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
})
