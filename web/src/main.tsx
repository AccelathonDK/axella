import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/hanken-grotesk/400.css'
import '@fontsource/hanken-grotesk/500.css'
import '@fontsource/hanken-grotesk/600.css'
import '@fontsource/hanken-grotesk/700.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import './index.css'
import App from './App'
import { installReportCapture } from '@/lib/report'

installReportCapture()   // errors as templates for Report a problem – kept in memory only

// iPhone, opened from the Home Screen: iOS lays out a fixed bottom bar against a too-short viewport until the first
// scroll or tap (the tab bar floats above the bottom edge). A 1-pixel scroll and back right after the page shows makes
// it measure again – nothing the eye can see.
const standalone = (navigator as Navigator & { standalone?: boolean }).standalone || matchMedia('(display-mode: standalone)').matches
if (standalone && /iPhone|iPad|iPod/.test(navigator.userAgent)) {
  // a short page (nothing to scroll) ignores scrollTo – so it is made 2 px taller for the nudge, then put back
  const settle = () => requestAnimationFrame(() => requestAnimationFrame(() => {
    const y = window.scrollY, root = document.documentElement, before = root.style.minHeight
    root.style.minHeight = 'calc(100vh + 2px)'
    window.scrollTo(0, y + 1); window.scrollTo(0, y)
    requestAnimationFrame(() => { root.style.minHeight = before })
  }))
  window.addEventListener('load', () => { settle(); setTimeout(settle, 400) })
  window.addEventListener('pageshow', settle)
  window.addEventListener('orientationchange', () => setTimeout(settle, 300))
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') setTimeout(settle, 50) })
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
