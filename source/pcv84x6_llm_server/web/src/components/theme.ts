/** Day/night theme: one attribute on <html>, remembered in localStorage.
 *
 *  Order of precedence: an explicit choice the operator made (localStorage) wins;
 *  otherwise the OS preference; otherwise light. The attribute is applied at
 *  module load, i.e. before React's first render, so switching pages or
 *  reloading never flashes the other palette. swappping themes never reloads the
 *  page, so an open session and any in-flight poll survive it.
 */

export type Theme = 'light' | 'dark'

export const THEME_KEY = 'cv84x6.theme'

export function storedTheme(): Theme | null {
  try {
    const v = localStorage.getItem(THEME_KEY)
    return v === 'light' || v === 'dark' ? v : null
  } catch {
    // Private mode / disabled storage: fall back to the OS preference.
    return null
  }
}

export function systemTheme(): Theme {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function initialTheme(): Theme {
  return storedTheme() ?? systemTheme()
}

export function applyTheme(theme: Theme, persist: boolean): void {
  const root = document.documentElement
  root.setAttribute('data-theme', theme)
  // Lets the browser paint its own widgets (scrollbars, form controls) in the
  // same palette instead of the OS default.
  root.style.colorScheme = theme
  if (!persist) return
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Without storage the choice just does not survive a reload.
  }
}

// Runs as soon as this module is evaluated -- see the note at the top.
applyTheme(initialTheme(), false)
