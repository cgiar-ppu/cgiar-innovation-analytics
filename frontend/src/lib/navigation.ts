/**
 * @file navigation.ts
 * @module lib
 *
 * Full-page navigation, isolated so tests can observe it (jsdom does not
 * implement `window.location.assign`). Used after sign-out so no in-memory
 * state of the previous user survives in the tab (L4-04).
 */
export const navigation = {
  hardNavigate(url: string): void {
    window.location.assign(url)
  },
}
