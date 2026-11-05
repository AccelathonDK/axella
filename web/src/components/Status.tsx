/* System status (account menu → System status, ?v=status): is every part of Axella running? One row per part – the
   Axella service, watchdog, your login session, web server, disk, Claude Code, Macuse, schedule, Mail, Messages,
   WhatsApp, Signal, call agent, notifications – with what to do when one isn't. GET system_status; when the Axella
   service itself doesn't answer, the web server's status.json (the watchdog's last check) says why. */
import { useCallback, useEffect, useState } from 'react'
import { Activity, RotateCw } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { cn } from '@/lib/utils'

type State = 'ok' | 'warn' | 'down' | 'off' | 'unknown'
interface Comp { group: string; id: string; name: string; state: State; detail: string; fix?: string | null; at?: string | null }
export interface Problem { id: string; name: string; state: State; what: string; since_text?: string | null; affects: string; fix?: string | null }
export interface Sentence { level: 'ok' | 'warn' | 'down'; text: string; short: string; problems: Problem[] }
const LABEL: Record<State, string> = { ok: 'OK', warn: 'Check', down: 'Not running', off: 'Not set up', unknown: 'Unknown' }
const DOT: Record<State, string> = { ok: 'bg-[var(--ax-success)]', warn: 'bg-dawn', down: 'bg-danger', off: 'bg-line-strong', unknown: 'bg-line-strong' }

let shortCache: { at: number; s: Sentence | null } | null = null
/** The short sentence for the account menu – asked at most every 5 minutes. */
export function useStatusShort(enabled: boolean) {
  const [s, setS] = useState<Sentence | null>(shortCache?.s || null)
  useEffect(() => {
    if (!enabled) return
    const f = () => {
      if (shortCache && Date.now() - shortCache.at < 300000) { setS(shortCache.s); return }
      get<{ sentence?: Sentence | null }>('system_status').then(j => { shortCache = { at: Date.now(), s: j.sentence || null }; setS(j.sentence || null) }).catch(() => {})
    }
    f(); const t = setInterval(() => !document.hidden && f(), 300000); return () => clearInterval(t)
  }, [enabled])
  return s
}

export function StatusView() {
  const { go } = useApp()
  const [d, setD] = useState<{ at: string; overall: State; components: Comp[]; sentence?: Sentence | null } | null>(null)
  const [analysis, setAnalysis] = useState(false)
  const [down, setDown] = useState<{ ok?: boolean | null; problem?: string | null; since?: string | null; session?: boolean | null } | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => {
    setBusy(true)
    try { const j = await get<{ at: string; overall: State; components: Comp[]; sentence?: Sentence | null }>('system_status'); setD(j); setDown(null) }
    catch {
      setD(null)
      const w = await fetch('status.json', { cache: 'no-store' }).then(r => r.ok ? r.json() : null).catch(() => null)
      setDown(w || {})
    } finally { setBusy(false) }
  }, [])
  useEffect(() => { load(); const t = setInterval(() => !document.hidden && load(), 30000); return () => clearInterval(t) }, [load])

  const groups = d ? [...new Set(d.components.map(c => c.group))] : []
  const bad = d ? d.components.filter(c => c.state === 'down' || c.state === 'warn') : []
  const time = (iso?: string | null) => iso ? new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : ''
  return <div className="space-y-4" data-status-view="">
    <div className="flex items-start gap-3">
      <div className="min-w-0 flex-1">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><Activity className="size-5" />System status</h1>
        <p className="text-muted-foreground text-sm">Every part Axella needs on the Mac mini, and what to do when one isn't running.{d && <> Checked {time(d.at)}.</>}</p>
      </div>
      <Button size="pill" variant="outline" onClick={load} disabled={busy}><RotateCw className={cn(busy && 'animate-spin')} />Check now</Button>
    </div>

    {down && <div className="bg-card rounded-lg border p-4 text-sm" data-status-down="">
      <div className="flex items-center gap-2 font-semibold"><span className="bg-danger size-2.5 rounded-full" />The Axella service on the Mac mini isn't answering</div>
      <p className="text-ink-2 mt-1">{down.problem
        ? <>{down.problem}{down.since && <> Since {time(down.since)}.</>}</>
        : down.ok === undefined || down.ok === null
          ? 'The watchdog isn’t installed, so the reason is unknown. Check on the Mac mini: is it on, and are you logged in?'
          : 'The watchdog sees no problem yet – the service may be restarting. Check again in a minute.'}</p>
      <p className="text-ink-3 mt-2 text-[13px]">The rest of the page shows what it loaded last. Fix: log in on the Mac mini (Screen Sharing → Log in as yourself). SETUP.md, Troubleshooting: "Dashboard shows 502".</p>
    </div>}

    {d && (d.sentence ? <div className={cn('rounded-lg border px-4 py-3 text-sm', d.sentence.level === 'down' ? 'bg-danger/10' : d.sentence.level === 'warn' ? 'bg-dawn/10' : 'bg-card')} data-status-sentence="">
        <div className="flex flex-wrap items-center gap-2">
          <span className={cn('size-2.5 shrink-0 rounded-full', d.sentence.level === 'ok' ? 'bg-[var(--ax-success)]' : d.sentence.level === 'warn' ? 'bg-dawn' : 'bg-danger')} aria-hidden />
          <b className="min-w-0 flex-1 font-semibold">{d.sentence.text}</b>
          {d.sentence.problems.length > 0 && <Button size="pill" variant="outline" onClick={() => setAnalysis(!analysis)} aria-expanded={analysis}>{analysis ? 'Hide analysis' : 'Show analysis'}</Button>}
        </div>
        {analysis && <div className="mt-3 space-y-3" data-status-analysis="">{d.sentence.problems.map(p => <div key={p.id} className="bg-card rounded-md border px-3 py-2.5">
          <div className="font-medium">{p.what}</div>
          {p.since_text && <div className="text-ink-2">{p.since_text}</div>}
          <div className="text-ink-2">{p.affects}</div>
          {p.fix && <div className="text-ink-3 mt-0.5 text-[12.5px]">What to do: {p.fix}</div>}
          <div className="mt-1.5 flex gap-2"><Button size="pill" variant="outline" onClick={load} disabled={busy}><RotateCw className={cn(busy && 'animate-spin')} />Check again</Button>
            <Button size="pill" variant="ghost" onClick={() => go({ kind: 'runs' })}>Recent runs</Button></div>
        </div>)}</div>}
      </div>
      : <div className={cn('rounded-lg border px-4 py-3 text-sm', bad.length ? 'bg-dawn/10' : 'bg-card')}>
      {bad.length ? <><b className="font-semibold">{bad.length} {bad.length === 1 ? 'part needs' : 'parts need'} a look:</b> {bad.map(c => c.name).join(', ')}.</>
        : <><b className="font-semibold">Everything is running.</b> <span className="text-ink-2">Parts that aren't set up are optional.</span></>}
    </div>)}

    {groups.map(g => <section key={g} className="bg-card overflow-hidden rounded-lg border">
      <div className="ax-label border-b px-4 py-2">{g}</div>
      <div className="divide-y">
        {d!.components.filter(c => c.group === g).map(c => <div key={c.id} className="flex items-start gap-3 px-4 py-2.5" data-comp={c.id} data-state={c.state}>
          <span className={cn('mt-[7px] size-2.5 shrink-0 rounded-full', DOT[c.state])} aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2"><span className="font-medium">{c.name}</span>
              <span className={cn('text-[12.5px]', c.state === 'down' ? 'text-danger' : c.state === 'warn' ? 'text-dawn' : 'text-ink-3')}>{LABEL[c.state]}</span></div>
            <div className="text-ink-2 text-[13px]">{c.detail}</div>
            {c.fix && c.state !== 'ok' && <div className="text-ink-3 mt-0.5 text-[12.5px]">{c.fix}</div>}
          </div>
        </div>)}
      </div>
    </section>)}

    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="outline" onClick={() => go({ kind: 'runs' })}>Runs and logs</Button>
      <Button size="sm" variant="ghost" onClick={() => go({ kind: 'settings', page: 'system' })}>Versions</Button>
    </div>
  </div>
}
