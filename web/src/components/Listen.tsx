import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { ChevronRight, Loader2, Pause, Play, X } from '@/components/ax-icons'
import { get } from '@/lib/api'
import { cn } from '@/lib/utils'

/* Listen: one queue – the spoken digest, then the briefs you haven't heard yet (api/listen).
   Each part is a real audio file made on the Mac mini (api/audio, macOS voices), so it keeps playing with the screen
   locked, and the lock screen, steering-wheel buttons and CarPlay get play/pause and next/previous (Media Session).
   A brief is split into its opening and one part per item, so "next" skips one item; "Next brief" skips the rest
   of a brief. Where the Mac mini can't make audio, the browser's own voice reads the text instead. */
export interface Seg { id: string; kind: 'digest' | 'brief'; brief?: string; title: string; album: string; text: string; lang?: string | null }
interface St { queue: Seg[]; i: number; playing: boolean; loading: boolean; audio: boolean }

let st: St = { queue: [], i: 0, playing: false, loading: false, audio: true }
const subs = new Set<(s: St) => void>()
const set = (x: Partial<St>) => { st = { ...st, ...x }; subs.forEach(f => f(st)); session() }
const el = typeof Audio !== 'undefined' ? new Audio() : null
if (el) { el.preload = 'auto'; (el as any).playsInline = true }

const HEARD = 'ax-heard-briefs', POS = 'ax-listen-pos'
const load = <T,>(k: string, d: T): T => { try { return JSON.parse(localStorage.getItem(k) || '') ?? d } catch { return d } }
const save = (k: string, v: unknown) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* private mode */ } }
const heard = () => new Set<string>(load<string[]>(HEARD, []))
const markHeard = (b?: string) => { if (!b) return; const h = [...heard()].filter(x => x !== b); h.push(b); save(HEARD, h.slice(-200)) }

export async function toggleListen() {
  if (st.playing) { pause(); return }
  if (st.queue.length && !st.loading) { resume(); return }
  await start()
}

export async function start(fromBrief?: string) {
  set({ loading: true })
  try {
    const j = await get<{ segments: Seg[]; audio: boolean }>('listen')
    const h = heard()
    let q = j.segments.filter(s => s.kind === 'digest' || !h.has(s.brief!) || s.brief === fromBrief)
    if (fromBrief) q = q.filter(s => s.brief === fromBrief)
    if (!q.length) { set({ loading: false }); toast('Nothing to listen to yet'); return }
    // carry on where you stopped, if it's the same queue
    const p = load<{ first?: string; id?: string; t?: number } | null>(POS, null)
    let i = 0, t = 0
    if (!fromBrief && p && p.first === q[0].id) { const k = q.findIndex(s => s.id === p.id); if (k > 0 || (k === 0 && (p.t || 0) > 5)) { i = k; t = p.t || 0 } }
    set({ queue: q, audio: j.audio && !!el, loading: false })
    play(i, t)
  } catch (e: any) { set({ loading: false }); toast.error('Couldn’t load Listen: ' + e.message) }
}

const url = (s: Seg) => 'api/audio?seg=' + encodeURIComponent(s.id)

function play(i: number, t = 0) {
  const s = st.queue[i]
  if (!s) { stop(true); return }
  speechSynthesis?.cancel()
  set({ i, playing: true })
  if (st.audio && el) {
    el.src = url(s)
    if (t) el.addEventListener('loadedmetadata', () => { try { el.currentTime = t } catch { /* */ } }, { once: true })
    el.play().catch(() => speak(s))
    const n = st.queue[i + 1]
    if (n) fetch(url(n), { headers: { Range: 'bytes=0-1' } }).catch(() => {})      // let the Mac mini make the next part now
  } else speak(s)
}

function speak(s: Seg) {
  if (!('speechSynthesis' in window)) { toast.error('This device can’t play the audio'); stop(); return }
  const lang = s.lang === 'da' ? 'da-DK' : 'en-GB'
  const voices = speechSynthesis.getVoices().filter(v => v.lang.toLowerCase().startsWith(lang.slice(0, 2)))
  const parts = s.text.replace(/\n+/g, ' ').match(/[^.!?]+[.!?]+["”’)]*\s*|[^.!?]+$/g) || [s.text]
  parts.forEach((p, k) => {
    const u = new SpeechSynthesisUtterance(p.trim()); u.lang = lang; u.rate = 0.97
    if (voices[0]) u.voice = voices.find(v => v.localService) || voices[0]
    if (k === parts.length - 1) u.onend = () => { if (st.playing && st.queue[st.i] === s) ended() }
    speechSynthesis.speak(u)
  })
}

function ended() {
  const s = st.queue[st.i], n = st.queue[st.i + 1]
  if (s?.kind === 'brief' && n?.brief !== s.brief) markHeard(s.brief)
  if (n) play(st.i + 1); else stop(true)
}

export function pause() { el?.pause(); speechSynthesis?.cancel(); set({ playing: false }) }
export function resume() { if (st.audio && el?.src) { el.play().catch(() => play(st.i)); set({ playing: true }) } else play(st.i) }
export function next() { const s = st.queue[st.i]; if (s?.kind === 'brief' && st.queue[st.i + 1]?.brief !== s.brief) markHeard(s.brief); play(st.i + 1) }
export function prev() { if (el && el.currentTime > 3) { el.currentTime = 0; return } play(Math.max(0, st.i - 1)) }
export function nextBrief() {
  const s = st.queue[st.i]
  if (s?.kind === 'brief') markHeard(s.brief)
  const k = st.queue.findIndex((x, j) => j > st.i && (x.kind !== s?.kind || x.brief !== s?.brief))
  if (k < 0) stop(true); else play(k)
}
export function stop(done = false) {
  el?.pause(); speechSynthesis?.cancel()
  if (el) el.removeAttribute('src')
  if (done) save(POS, null)
  set({ queue: [], i: 0, playing: false })
}

if (el) {
  el.addEventListener('ended', ended)
  el.addEventListener('error', () => { const s = st.queue[st.i]; if (s && st.playing && el.getAttribute('src')) speak(s) })
  let last = 0
  el.addEventListener('timeupdate', () => {
    if (Date.now() - last < 3000 || !st.queue.length) return
    last = Date.now()
    save(POS, { first: st.queue[0].id, id: st.queue[st.i]?.id, t: Math.floor(el.currentTime) })
    try { if (el.duration && isFinite(el.duration)) navigator.mediaSession?.setPositionState?.({ duration: el.duration, position: el.currentTime, playbackRate: 1 }) } catch { /* */ }
  })
}

/* lock screen, steering wheel, CarPlay audio */
function session() {
  const ms = navigator.mediaSession
  if (!ms) return
  const s = st.queue[st.i]
  if (!s) { ms.metadata = null; ms.playbackState = 'none'; return }
  ms.metadata = new MediaMetadata({ title: s.title, artist: 'Axella', album: s.album,
    artwork: [{ src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png' }, { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' }] })
  ms.playbackState = st.playing ? 'playing' : 'paused'
}
if (typeof navigator !== 'undefined' && navigator.mediaSession) {
  const ms = navigator.mediaSession
  const h: [MediaSessionAction, MediaSessionActionHandler][] = [
    ['play', () => resume()], ['pause', () => pause()], ['stop', () => stop()],
    ['nexttrack', () => next()], ['previoustrack', () => prev()],
    ['seekforward', () => { if (el) el.currentTime = Math.min((el.duration || 0), el.currentTime + 15) }],
    ['seekbackward', () => { if (el) el.currentTime = Math.max(0, el.currentTime - 15) }],
  ]
  h.forEach(([a, f]) => { try { ms.setActionHandler(a, f) } catch { /* not supported */ } })
}

export function useListen() {
  const [s, setS] = useState(st)
  useEffect(() => { subs.add(setS); return () => { subs.delete(setS) } }, [])
  return s
}
export function useListening() { return useListen().playing }

/* the small player above the tab bar / footer while something is queued */
export function ListenBar() {
  const s = useListen()
  if (!s.queue.length && !s.loading) return null
  const cur = s.queue[s.i]
  const n = s.queue.length
  const inBrief = cur?.kind === 'brief'
  return <div role="region" aria-label="Listen" className="pointer-events-none fixed inset-x-0 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] z-30 flex justify-center px-3 lg:bottom-[calc(2.75rem)] lg:left-[248px]">
    <div className="ax-reveal bg-surface-inverse text-on-inverse pointer-events-auto flex w-full max-w-xl items-center gap-2 rounded-lg py-2 pr-2 pl-2 shadow-lg">
      <button onClick={() => s.playing ? pause() : resume()} disabled={s.loading} aria-label={s.playing ? 'Pause' : 'Play'}
        className="bg-on-inverse text-surface-inverse flex size-10 shrink-0 items-center justify-center rounded-md">
        {s.loading ? <Loader2 className="size-5 animate-spin" /> : s.playing ? <Pause className="size-5" /> : <Play className="size-5" />}</button>
      <div className="min-w-0 flex-1 px-1">
        <div className="truncate font-mono text-[11px] tracking-[.08em] uppercase opacity-70">{cur ? cur.album : 'Listen'}{n > 1 ? ` · ${s.i + 1}/${n}` : ''}</div>
        <div className="truncate text-sm font-medium">{cur ? cur.title : 'Getting it ready…'}</div>
      </div>
      {inBrief && <button onClick={nextBrief} className="shrink-0 rounded-md px-2 py-1.5 text-[13px] font-medium opacity-80 hover:opacity-100 max-[420px]:hidden">Next brief</button>}
      <button onClick={next} aria-label="Next" disabled={s.i >= n - 1} className={cn('shrink-0 rounded-md p-2 opacity-80 hover:opacity-100', s.i >= n - 1 && 'opacity-30')}><ChevronRight className="size-5" /></button>
      <button onClick={() => stop()} aria-label="Stop" className="shrink-0 rounded-md p-2 opacity-60 hover:opacity-100"><X className="size-4" /></button>
    </div>
  </div>
}
