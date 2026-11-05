import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Loader2, axi } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { get, post } from '@/lib/api'
import { privacyRender, realRender, snapshot, track } from '@/lib/report'
import { cn } from '@/lib/utils'

/* Report a problem (Cmd/Ctrl+B, the account menu, or a long press on the Axella mark on the phone).
   Saved at home first (Settings → Reports); sending is a separate tap after a full preview. In community mode only the
   anonymised payload leaves (setup/reports.py payload()); in developer mode – the owner's own instance – the full
   report stays in the reports/ folder on the Mac mini. */
export const CLASSES = [['critical', 'Critical'], ['annoying', 'Annoying'], ['cosmetic', 'Cosmetic'], ['missing', 'Missing']] as const
export type RClass = typeof CLASSES[number][0]
export const ReportIcon = axi('report')
export const openReport = () => window.dispatchEvent(new Event('ax-report'))
interface Flag { start: number; end: number; kind: string; text: string }
interface Ctx { meta: Record<string, unknown>; errors: { message: string; frames: string[]; source?: string }[]; mode: 'developer' | 'community'; intake: string }

export function useReportShortcut() {
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'b') { e.preventDefault(); openReport() }
    }
    addEventListener('keydown', k); return () => removeEventListener('keydown', k)
  }, [])
}

/** Long press (0.7 s) – for the Axella mark on the phone. */
export function longPress(fn: () => void) {
  let t: number | undefined
  const stop = () => clearTimeout(t)
  return { onPointerDown: () => { t = window.setTimeout(fn, 700) }, onPointerUp: stop, onPointerLeave: stop, onPointerCancel: stop,
    onContextMenu: (e: React.MouseEvent) => e.preventDefault() }
}

export function ReportHost() {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [text, setText] = useState(''), [cls, setCls] = useState<RClass | null>(null), [suggested, setSuggested] = useState<RClass>('annoying')
  const [withRender, setWithRender] = useState(true), [reply, setReply] = useState('')
  const [render, setRender] = useState<string | null>(null), [full, setFull] = useState<string | null>(null)
  const [ctx, setCtx] = useState<Ctx | null>(null), [flags, setFlags] = useState<Flag[]>([])
  const [preview, setPreview] = useState<any>(null), [saved, setSaved] = useState<string | null>(null)
  const snap = useRef<ReturnType<typeof snapshot> | null>(null)
  const route = useRef('unknown')

  useEffect(() => {
    const go = async () => {
      if (open) return
      route.current = (new URLSearchParams(location.search).get('v') || 'today').replace(/[^a-z_-]/g, '').slice(0, 30) || 'today'
      track('report', 'open')
      snap.current = snapshot()
      setText(''); setCls(null); setSuggested('annoying'); setFlags([]); setPreview(null); setSaved(null); setReply(''); setWithRender(true)
      // the screen as it is now – drawn before the dialog covers it
      const t = toast.loading('Preparing the report…')
      const c = await get<Ctx>('report_context').catch(() => null)
      let r: string | null = null, f: string | null = null
      try { r = await privacyRender() } catch { r = null }
      if (c?.mode === 'developer') { try { f = await realRender() } catch { f = null } }
      toast.dismiss(t)
      setCtx(c); setRender(r); setFull(f); setBusy(null); setOpen(true)
    }
    const h = () => { go() }
    addEventListener('ax-report', h); return () => removeEventListener('ax-report', h)
  }, [open])

  // the text check: names from your contacts, e-mail, phone, card numbers, personal links – and a suggested class
  useEffect(() => {
    if (!open || !text.trim()) { setFlags([]); return }
    const t = setTimeout(() => {
      post<{ result: { flags: Flag[]; suggested: RClass } }>('report_check', { text })
        .then(r => { setFlags(r.result.flags); setSuggested(r.result.suggested) }).catch(() => {})
    }, 500)
    return () => clearTimeout(t)
  }, [text, open])

  const dev = ctx?.mode === 'developer'
  const body = useCallback(() => ({
    id: saved || undefined, text, class: cls || suggested, suggested, route: route.current, trail: snap.current?.trail, include_render: withRender,
    errors: [...(snap.current?.errors || []).map(e => ({ ...e, source: 'app' })), ...(ctx?.errors || [])],
    meta: { ...(snap.current?.meta || {}), ...(ctx?.meta || {}) },
    ...(saved ? {} : { render: render || undefined, full: dev ? full || undefined : undefined }),
  }), [saved, text, cls, suggested, withRender, ctx, render, full, dev])

  async function keep(quiet = false) {
    if (!text.trim()) { toast.warning('Say what happened (or what is missing) first'); return null }
    setBusy('save')
    try {
      const r = await post<{ result: { id: string } }>('report_save', body())
      setSaved(r.result.id)
      if (!quiet) { toast('Saved on the Mac mini – Settings → Reports'); setOpen(false) }
      return r.result.id
    } catch (e: any) { toast.error('Not saved: ' + e.message); return null } finally { setBusy(null) }
  }
  async function showPreview() {
    const id = await keep(true); if (!id) return               // saves the latest edits first – the preview is of what's stored
    setBusy('preview')
    try { setPreview((await post<{ result: unknown }>('report_preview', { id, reply })).result) } catch (e: any) { toast.error(e.message) } finally { setBusy(null) }
  }
  async function send() {
    if (!dev && !preview) { await showPreview(); return }        // community: nothing leaves before you've seen it
    const id = dev ? await keep(true) : saved; if (!id) return   // (any edit after the preview clears it again)
    setBusy('send')
    try {
      const r: any = (await post('report_send', { id, reply })).result
      toast(dev ? 'Full report saved in reports/ on the Mac mini' : `Sent – thank you. Code ${r.code || ''}`, { duration: 8000 })
      setOpen(false)
    } catch (e: any) { toast.error('Not sent: ' + e.message + ' – it stays saved in Settings → Reports') } finally { setBusy(null) }
  }

  const marked = flags.length > 0
  return <Dialog open={open} onOpenChange={setOpen}>
    <DialogContent data-report-dialog="" className="sm:max-w-xl"><div className="overflow-y-auto px-5 pt-4 pb-5">
      <DialogTitle className="text-lg font-semibold">Report a problem</DialogTitle>
      <p className="text-ink-3 -mt-1 text-[13px]">{dev ? 'Developer mode: the full report – with the real screen – stays in reports/ on the Mac mini.'
        : 'Your messages never leave your home. This report shows the layout, not your content.'}</p>

      <label className="mt-2 grid gap-1 text-[13px] font-medium">What happened – or what's missing?
        <textarea autoFocus value={text} onChange={e => { setText(e.target.value); setPreview(null) }} rows={4} maxLength={4000}
          className="border-input bg-card focus-visible:ring-ring/50 rounded-md border px-3 py-2 text-[15px] font-normal leading-relaxed outline-none focus-visible:ring-2" /></label>
      {marked && !dev && <div className="bg-dawn/15 rounded-md px-3 py-2 text-[13px]">
        <div>This looks personal – remove it before sending?</div>
        <div className="mt-1.5 flex flex-wrap gap-1.5">{flags.map((f, i) => <button key={i} type="button" title={'Remove ' + f.kind}
          className="bg-card hover:bg-bg-2 rounded-sm border px-1.5 py-0.5 text-[12px]" onClick={() => { setText(t => t.slice(0, f.start) + '…' + t.slice(f.end)); setPreview(null) }}>
          <span className="text-ink-3">{f.kind}:</span> {f.text} ✕</button>)}</div></div>}

      <div className="mt-3">
        <div className="ax-label mb-1.5">Kind</div>
        <div role="radiogroup" className="bg-bg-2 inline-flex flex-wrap rounded-md border p-0.5">
          {CLASSES.map(([k, l]) => <button key={k} type="button" role="radio" aria-checked={(cls || suggested) === k} onClick={() => { setCls(k); setPreview(null) }}
            className={cn('rounded px-3 py-1 text-[13px]', (cls || suggested) === k ? 'bg-card text-ink font-semibold shadow-sm' : 'text-ink-2 hover:text-ink')}>
            {l}{!cls && suggested === k && <span className="text-ink-3 font-normal"> · suggested</span>}</button>)}
        </div>
      </div>

      <label className="mt-3 flex items-center gap-2 text-[13px]"><input type="checkbox" className="accent-fjord size-4" checked={withRender}
        onChange={e => { setWithRender(e.target.checked); setPreview(null) }} />Include the privacy render (layout only, every text replaced)</label>
      <div className="bg-bg-2 mt-2 flex min-h-24 items-center justify-center overflow-hidden rounded-md border">
        {busy === 'render' ? <span className="text-ink-3 flex items-center gap-2 text-[13px]"><Loader2 className="size-4 animate-spin" />Drawing the privacy render…</span>
          : render && withRender ? <img src={render} alt="Privacy render of the screen" className="max-h-56 w-full object-contain" />
          : <span className="text-ink-3 text-[13px]">{withRender ? 'No render could be made' : 'No render'}</span>}
      </div>

      {!dev && <label className="mt-3 grid gap-1 text-[13px]"><span className="font-medium">Reply address <span className="text-ink-3 font-normal">optional – kept apart from the report, never published</span></span>
        <Input type="email" value={reply} onChange={e => { setReply(e.target.value); setPreview(null) }} placeholder="you@example.com" /></label>}

      {preview && <div className="mt-3 rounded-md border">
        <div className="bg-bg-2 border-b px-3 py-1.5 text-[12px] font-semibold">Exactly what will be sent</div>
        <pre className="max-h-64 overflow-auto px-3 py-2 font-mono text-[11.5px] leading-snug whitespace-pre-wrap">{JSON.stringify(preview, null, 1)}</pre>
      </div>}
      <p className="text-ink-3 mt-2 text-[12px]">{dev ? 'Saved reports are in Settings → Reports.' : 'Axella makes everything she adds anonymous. What you type is checked, but what you send is your choice.'}</p>

      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        {!dev && <Button variant="ghost" size="sm" onClick={() => showPreview()} disabled={!!busy}>{busy === 'preview' && <Loader2 className="animate-spin" />}Preview what's sent</Button>}
        <Button variant="outline" size="sm" onClick={() => keep()} disabled={!!busy}>{busy === 'save' && <Loader2 className="animate-spin" />}Keep locally</Button>
        <Button size="sm" onClick={send} disabled={!!busy || busy === 'render'}>{busy === 'send' && <Loader2 className="animate-spin" />}
          {dev ? 'Save full report' : preview ? 'Send' : 'Preview and send'}</Button>
      </div>
    </div></DialogContent>
  </Dialog>
}

/* ---------- Settings → Reports: everything you reported, and (maintainer only) community triage ---------- */
interface Saved { id: string; at: string; class: RClass | null; text: string; route: string; status: string; mode: string; has_render: boolean; has_full: boolean
  sent_at?: string; code?: string; status_url?: string; issue_url?: string; remote_status?: string }
interface Community { id: string; created: string; class: RClass; text: string; route: string; status: string; meta?: Record<string, unknown>
  trail?: string[]; errors?: { message: string }[]; issue_url?: string | null; duplicate_of?: string | null }
const STATUS: Record<string, string> = { kept: 'kept locally', draft: 'draft', sent: 'sent', promoted: 'on GitHub' }
const LABEL = Object.fromEntries(CLASSES) as Record<string, string>

export function ReportsCard() {
  const [d, setD] = useState<{ reports: Saved[]; mode: string; triage: boolean } | null>(null)
  const [tab, setTab] = useState<'mine' | 'community'>('mine')
  const [open, setOpen] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const load = useCallback(() => get<{ reports: Saved[]; mode: string; triage: boolean }>('reports')
    .then(j => setD({ ...j, reports: Array.isArray(j.reports) ? j.reports : [], mode: j.mode || 'community', triage: !!j.triage })).catch(() => {}), [])
  useEffect(() => { load() }, [load])
  if (!d) return null
  const act = async (a: string, body: object, ok: string) => {
    setBusy(a + JSON.stringify(body))
    try { const r: any = await post(a, body); if (ok) toast(ok); await load(); return r.result } catch (e: any) { toast.error(e.message) } finally { setBusy(null) }
  }
  const day = (s?: string) => s ? new Date(s).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''
  return <div id="sec-reports" className="bg-card overflow-hidden rounded-lg border">
    <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
      <ReportIcon className="text-ink-3 size-[18px]" /><span className="font-semibold">Reports</span>
      <span className="text-ink-3 text-[13px]">{d.mode === 'developer' ? 'developer mode – full reports stay in reports/' : 'anonymised when sent'}</span>
      <span className="ml-auto flex gap-2">
        {/* one folder per report: report.md + pictures – ready to hand to Claude */}
        {(tab === 'community' || d.reports.length > 0) && <Button size="sm" variant="ghost" asChild>
          <a href={tab === 'community' ? 'api/reports_zip?community=1&ids=-' : 'api/reports_zip'} download>Download for Claude (.zip)</a></Button>}
        <Button size="sm" variant="outline" onClick={openReport}><ReportIcon />Report a problem</Button></span>
    </div>
    {d.triage && <div className="flex gap-1 border-b px-3 py-2 text-[13px]">
      {(['mine', 'community'] as const).map(t => <button key={t} onClick={() => setTab(t)} className={cn('rounded px-2.5 py-1', tab === t ? 'bg-bg-2 font-semibold' : 'text-ink-2 hover:text-ink')}>
        {t === 'mine' ? 'My reports' : 'Community reports'}</button>)}</div>}
    {tab === 'community' ? <Triage /> : !d.reports.length ? <p className="text-ink-3 px-4 py-3 text-[13px]">No reports yet. Press {/Mac/.test(navigator.platform) ? '⌘B' : 'Ctrl+B'} anywhere when something's wrong or missing.</p>
      : <ul className="divide-y">{d.reports.map(r => <li key={r.id} className="px-4 py-2.5 text-[13px]">
        <button className="flex w-full items-start gap-2 text-left" onClick={() => setOpen(open === r.id ? null : r.id)}>
          <span className={cn('shrink-0 rounded-sm px-1.5 text-[11px] font-semibold uppercase', r.class === 'critical' ? 'bg-dawn text-on-dawn' : 'bg-bg-2 text-ink-2')}>{LABEL[r.class || 'annoying']}</span>
          <span className="min-w-0 flex-1 truncate">{r.text}</span>
          <span className="text-ink-3 shrink-0">{r.issue_url ? 'on GitHub' : STATUS[r.status] || r.status} · {day(r.at)}</span>
        </button>
        {open === r.id && <div className="mt-2 space-y-2 pl-1">
          <div className="text-ink-3">Screen: {r.route || '–'}{r.code ? ` · code ${r.code}` : ''}{r.remote_status ? ` · ${r.remote_status}` : ''}</div>
          {r.has_render && <img src={`api/report_img?id=${r.id}&kind=render`} alt="Privacy render" className="max-h-48 rounded border" />}
          {r.has_full && <a className="text-fjord block hover:underline" href={`api/report_img?id=${r.id}&kind=full`} target="_blank" rel="noopener">The real screen (developer mode)</a>}
          <div className="flex flex-wrap gap-2">
            {r.issue_url && <a className="text-fjord font-semibold hover:underline" href={r.issue_url} target="_blank" rel="noopener noreferrer">Open the GitHub issue</a>}
            {r.status !== 'sent' && r.status !== 'promoted' && d.mode !== 'developer' && <Button size="sm" variant="outline" disabled={!!busy} onClick={async () => {
              const pv = await act('report_preview', { id: r.id }, '')
              if (pv && confirm('Send this anonymised report?\n\n' + JSON.stringify(pv, null, 1).slice(0, 1500))) act('report_send', { id: r.id }, 'Sent – thank you')
            }}>Preview and send</Button>}
            {r.code && <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => act('report_status', { id: r.id }, '')}>Check status</Button>}
            <Button size="sm" variant="ghost" asChild><a href={`api/reports_zip?ids=${r.id}`} download>Download (.zip)</a></Button>
            <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => act('report_discard', { id: r.id }, 'Moved to reports/_discarded')}>Discard</Button>
          </div>
        </div>}
      </li>)}</ul>}
    {d.mode !== 'developer' && tab === 'mine' && <div className="text-ink-3 flex flex-wrap items-center gap-2 border-t px-4 py-2.5 text-[12px]">
      Sent reports carry a random install token (for rate limiting only, not tied to you).
      <button className="text-fjord font-semibold hover:underline" onClick={() => act('report_rotate', {}, 'New install token – earlier reports can no longer be linked to this one')}>Make a new one</button></div>}
  </div>
}

function Triage() {
  const [list, setList] = useState<Community[] | null>(null), [err, setErr] = useState<string | null>(null)
  const [edit, setEdit] = useState<Record<string, { title: string; text: string; class: RClass }>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const load = useCallback(() => get<{ reports: Community[] }>('triage_list').then(j => { setList(j.reports); setErr(null) }).catch(e => setErr(e.message)), [])
  useEffect(() => { load() }, [load])
  const act = async (id: string, body: object, ok: string) => {
    setBusy(id)
    try { const r: any = await post('triage_act', { id, ...body }); toast(ok + (r.result?.issue_url ? ' – ' + r.result.issue_url : '')); await load() } catch (e: any) { toast.error(e.message) } finally { setBusy(null) }
  }
  if (err) return <p className="text-destructive px-4 py-3 text-[13px]">Couldn't reach the intake: {err}</p>
  if (!list) return <p className="text-ink-3 flex items-center gap-2 px-4 py-3 text-[13px]"><Loader2 className="size-4 animate-spin" />Loading…</p>
  if (!list.length) return <p className="text-ink-3 px-4 py-3 text-[13px]">Nothing waiting for triage.</p>
  return <ul className="divide-y">{list.map(r => {
    const e = edit[r.id] || { title: r.text.split('\n')[0].slice(0, 80), text: r.text, class: r.class }
    const set = (x: Partial<typeof e>) => setEdit(m => ({ ...m, [r.id]: { ...e, ...x } }))
    return <li key={r.id} className="space-y-2 px-4 py-3 text-[13px]">
      <div className="text-ink-3">{new Date(r.created).toLocaleString('en-GB')} · {r.route} · {String(r.meta?.app_version || '')} · {String(r.meta?.os || '')} {String(r.meta?.mac_model || '')}</div>
      <Input value={e.title} onChange={x => set({ title: x.target.value })} aria-label="Issue title" />
      <textarea value={e.text} onChange={x => set({ text: x.target.value })} rows={3} className="border-input bg-card w-full rounded-md border px-3 py-2" />
      <div className="flex flex-wrap items-center gap-2">
        <div className="bg-bg-2 inline-flex rounded-md border p-0.5">{CLASSES.map(([k, l]) => <button key={k} onClick={() => set({ class: k })}
          className={cn('rounded px-2 py-0.5', e.class === k ? 'bg-card font-semibold' : 'text-ink-2')}>{l}</button>)}</div>
        <a className="text-fjord hover:underline" href={`api/triage_render?id=${r.id}`} target="_blank" rel="noopener">Privacy render</a>
        {!!r.errors?.length && <span className="text-ink-3">{r.errors.length} error{r.errors.length === 1 ? '' : 's'}</span>}
        <span className="ml-auto flex gap-2">
          <Button size="sm" disabled={busy === r.id} onClick={() => act(r.id, { action: 'approve', ...e }, 'Issue created')}>Approve → GitHub</Button>
          <Button size="sm" variant="outline" disabled={busy === r.id} onClick={() => { const into = prompt('Duplicate of which report id?'); if (into) act(r.id, { action: 'merge', into }, 'Merged') }}>Merge…</Button>
          <Button size="sm" variant="ghost" disabled={busy === r.id} onClick={() => act(r.id, { action: 'discard' }, 'Discarded')}>Discard</Button>
        </span>
      </div>
      <div className="text-ink-3 font-mono text-[11px]">{r.id}</div>
    </li>
  })}</ul>
}
