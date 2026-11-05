import { SendLaterButton, scheduleSend } from '@/components/SendLater'
import { AttachButton, AttachList, SendButton, useAttachments } from '@/components/Send'
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { AlertTriangle, Copy, Loader2, MailPlus, RotateCcw, Save, Sparkles, Wand2 } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input, NativeSelect } from '@/components/ui/input'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useApp } from '@/lib/app'
import { get, newSendId, post } from '@/lib/api'
import { accLabel, profile } from '@/lib/profile'
import { BasedOn, KnowledgeIcon } from '@/components/Knowledge'
import { openKnowledge } from '@/lib/knowledge'
import { cn, isoDate, store } from '@/lib/utils'
import { AssistPanel, type AssistTarget } from '@/components/Assist'

interface Contact { address: string; name: string; count: number; account?: string }
interface Variant { label: string; text: string }
interface Result { to: string; name?: string; account: string; language?: string; subject: string; variants: Variant[]; context?: string; warnings?: string[]; kb?: string[] }
type Status = { state: 'queued'; position: number; waiting_for?: string | null } | { state: 'running' } | { state: 'failed'; error: string } | { state: 'done'; result: Result } | { state: 'unknown' }

const area = 'border-line-strong bg-card focus-visible:border-ring focus-visible:ring-ring/30 w-full rounded-md border px-2.5 py-1.5 text-[16px] outline-none focus-visible:ring-2 sm:text-sm'
const TONES = ['my usual tone', 'more formal', 'warm and personal', 'short and direct']

export type ComposePrefill = { to?: string; topic?: string; target?: string; notes?: string; account?: string; subject?: string; body?: string
  /** open on "Let Axella draft it" (Draft a note on a person's page) */
  mode?: 'ai' | 'self'; tone?: string }
export function ComposeDialog({ onClose, init }: { onClose: () => void; init?: ComposePrefill }) {
  const { ax } = useApp()
  const [contacts, setContacts] = useState<Contact[]>([])
  const defAcc = (profile().accounts.find(a => a.kind === 'private') || profile().accounts[0])?.id || 'iCloud'
  const [f, setF] = useState({ to: init?.to || '', topic: init?.topic || '', target: init?.target || '', tone: init?.tone && TONES.includes(init.tone) ? init.tone : TONES[0], language: 'auto',
    account: init?.account && profile().accounts.some(a => a.id === init.account) ? init.account : defAcc, notes: init?.notes || '' })
  const [id, setId] = useState<string | null>(null)
  const [st, setSt] = useState<Status | null>(null)
  const [since, setSince] = useState(0)
  const [res, setRes] = useState<Result | null>(null)
  const [pick, setPick] = useState(0)
  const [texts, setTexts] = useState<string[]>([])
  const [subject, setSubject] = useState(init?.subject || '')
  const [rework, setRework] = useState('')
  const [saving, setSaving] = useState(false)
  const att = useAttachments()
  // write it yourself (with the writing assistant if you want it) or let Axella draft it – the last choice is kept
  // a prefilled text (e.g. a meeting agenda) opens in Write it myself
  const [mode, setModeState] = useState<'self' | 'ai'>(() => init?.mode ? init.mode : init?.body ? 'self' : store.get('ax-compose-mode', 'self') === 'ai' ? 'ai' : 'self')
  const setMode = (m: 'self' | 'ai') => { setModeState(m); store.set('ax-compose-mode', m) }
  const [own, setOwn] = useState(init?.body || '')
  const [assist, setAssist] = useState(false)
  const ownBox = useRef<HTMLTextAreaElement>(null)
  const ownRef = useRef(own); ownRef.current = own
  const ownTarget: AssistTarget = useMemo(() => ({
    get text() { return ownRef.current },
    getSelection: () => { const el = ownBox.current; return el && el.selectionEnd > el.selectionStart ? { start: el.selectionStart, end: el.selectionEnd } : null },
    setText: (t: string) => setOwn(t),
    focus: (a: number, b: number) => { const el = ownBox.current; if (el) { el.focus(); el.setSelectionRange(a, b) } },
  }), [])
  const [, tick] = useState(0)
  const alive = useRef(true)
  useEffect(() => () => { alive.current = false }, [])
  useEffect(() => { get<{ contacts: Contact[] }>('compose_contacts').then(r => setContacts(r.contacts || [])).catch(() => {}) }, [])

  const known = useMemo(() => contacts.find(c => c.address === f.to.trim().toLowerCase()), [contacts, f.to])
  // one address or several (comma-separated – a meeting follow-up to everyone); [] when any of them isn't an address
  const toList = useMemo(() => { const l = f.to.split(/[,;]/).map(x => x.trim()).filter(Boolean)
    return l.length && l.length <= 20 && l.every(x => /^[^@\s<>"]+@[^@\s<>"]+\.[^@\s<>"]+$/.test(x)) ? l : [] }, [f.to])
  useEffect(() => { if (known?.account && profile().accounts.some(a => a.id === known.account)) setF(x => ({ ...x, account: known.account! })) }, [known])

  // poll the Mac mini until the draft is written
  useEffect(() => {
    if (!id) return
    let stop = false
    const t0 = Date.now(); setSince(t0)
    const timer = setInterval(() => tick(n => n + 1), 1000)
    ;(async () => {
      for (let i = 0; i < 400 && !stop && alive.current; i++) {
        const s = await get<Status>('compose?id=' + id).catch(() => null)
        if (s) {
          setSt(s)
          if (s.state === 'done') {
            const r = s.result
            setRes(r); setPick(0); setTexts(r.variants.map(v => v.text)); setSubject(r.subject); setId(null); return
          }
          if (s.state === 'failed') { setId(null); return }
        }
        await new Promise(r => setTimeout(r, 2000))
      }
    })()
    return () => { stop = true; clearInterval(timer) }
  }, [id])

  const start = async (revise?: { draft: string; subject: string; instruction: string }) => {
    try {
      const r = await post<{ result: { id: string } }>('compose', { ...f, name: known?.name || '', revise })
      setSt({ state: 'queued', position: 0 }); setId(r.result.id)
    } catch (e: any) { toast.error(e.message) }
  }
  // what Save / Send use: Axella's draft, or the mail you wrote yourself
  const cur = mode === 'self' ? { to: f.to.trim(), name: known?.name, account: f.account } : res
  const body = mode === 'self' ? own : texts[pick]
  const save = async () => {
    if (!cur) return
    setSaving(true)
    try {
      const r = await ax.act('draft_new', { account: cur.account, to: cur.to, subject, text: body }, [])
      if (!r?.result?.pending) toast.success('Saved to Drafts in ' + accLabel(cur.account) + ' – send it from Mail')
      onClose()
    } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setSaving(false) }
  }
  const send = async (force = false): Promise<void> => {
    if (!cur) return
    try {
      const r: any = await ax.act('mail_send', { account: cur.account, to: cur.to, subject, text: body, title: subject, confirm: 'send', attachments: att.ids, force, send_id: newSendId() }, [])
      if (!r?.result?.pending) toast.success('Sent to ' + (cur.name || cur.to))
      onClose()
    } catch (e: any) {
      if (/already sent/.test(String(e.message))) toast.warning('Not sent – ' + e.message, { duration: 20000, action: { label: 'Send again', onClick: () => { send(true) } } })
      else throw e
    }
  }
  const later = async (at: string) => {
    if (!cur) return
    await scheduleSend('mail_send', { account: cur.account, to: cur.to, subject, text: body, title: subject, attachments: att.ids }, at, cur.name || cur.to)
    onClose()
  }
  const busy = !!id
  const secs = since ? Math.round((Date.now() - since) / 1000) : 0

  return (
    <Dialog open onOpenChange={o => !o && onClose()}>
      <DialogContent>
        <div className="border-b px-5 py-3.5 pr-12">
          <DialogTitle className="flex items-center gap-2 text-base font-semibold"><MailPlus className="size-4" />New mail</DialogTitle>
          <div className="text-muted-foreground text-xs">{mode === 'self' ? 'You write it · the writing assistant helps if you ask · you send it from here' : 'Axella drafts it in your tone · you edit · you send it from here'}</div>
          {!res && !busy && <span className="bg-bg-2 mt-2.5 inline-flex rounded-md border p-0.5 text-[13px]" role="group" aria-label="How to write it" data-compose-mode="">
            {([['self', 'Write it myself'], ['ai', 'Axella drafts it']] as const).map(([m, l]) => <button key={m} type="button" onClick={() => setMode(m)} aria-pressed={mode === m}
              className={cn('rounded px-2.5 py-1', mode === m ? 'bg-card text-ink font-semibold shadow-sm' : 'text-ink-3 hover:text-ink')}>{m === 'ai' && <Sparkles className="mr-1 inline size-3.5 align-[-2px]" />}{l}</button>)}
          </span>}
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto p-5 text-sm">
          {mode === 'self' && !res && <div className="space-y-3" data-compose-self="">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_200px]">
              <label className="block"><span className="mb-1 block font-medium">To</span>
                <Input list="ax-compose-contacts" type="email" required value={f.to} placeholder="name@example.com" autoFocus={!f.to}
                  onChange={e => setF({ ...f, to: e.target.value })} />
                <datalist id="ax-compose-contacts">{contacts.map(c => <option key={c.address} value={c.address}>{c.name}</option>)}</datalist>
                {known?.name && <span className="text-muted-foreground mt-1 block text-xs">{known.name}</span>}
              </label>
              <label className="block"><span className="mb-1 block font-medium">From</span>
                <NativeSelect value={f.account} onChange={e => setF({ ...f, account: e.target.value })}>
                  {profile().accounts.map(a => <option key={a.id} value={a.id}>{a.label}{a.kind === 'private' ? ' (private)' : ''}</option>)}</NativeSelect></label>
            </div>
            <label className="block"><span className="mb-1 block font-medium">Subject</span><Input value={subject} maxLength={300} autoFocus={!!f.to} onChange={e => setSubject(e.target.value)} /></label>
            <div className={cn(assist && 'lg:grid lg:grid-cols-[1fr_300px] lg:gap-4')}>
              <textarea ref={ownBox} rows={12} className={area + ' font-[inherit] leading-relaxed'} value={own} placeholder="Write your mail…"
                onChange={e => setOwn(e.target.value)} aria-label="Your mail" />
              {assist && <div className="mt-3 lg:mt-0"><AssistPanel target={ownTarget} account={f.account} title={subject} to={f.to.trim()} onClose={() => setAssist(false)} /></div>}
            </div>
            <div className="-mt-1 flex flex-wrap items-center gap-3 text-[13px]">
              <AttachButton onFiles={att.add} />
              {!assist && <button type="button" onClick={() => setAssist(true)} className="text-fjord inline-flex items-center gap-1 font-medium hover:underline"><Sparkles className="size-3.5" />Writing assistant</button>}
              {!!att.list.length && <span className="text-ink-3">Attachments go with Send, not with Save to Drafts</span>}</div>
            <div className="-mx-4"><AttachList list={att.list} onRemove={att.remove} /></div>
            <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
              <Button variant="outline" onClick={save} disabled={saving || !subject.trim() || !own.trim() || toList.length !== 1}>{saving ? <Loader2 className="animate-spin" /> : <Save />}Save to Drafts</Button>
              <SendLaterButton to={toList.length > 1 ? toList.length + ' people' : known?.name || f.to.trim() || 'them'} disabled={saving || !subject.trim() || !own.trim() || att.busy || !toList.length} onSchedule={later} />
              <SendButton size="default" to={toList.length > 1 ? toList.length + ' people' : (known?.name || f.to.trim()).split(/\s+/)[0] || 'them'} disabled={saving || !subject.trim() || !own.trim() || att.busy || !toList.length} onSend={() => send()} />
            </div>
          </div>}
          {mode === 'ai' && !res && <form className="space-y-3" onSubmit={e => { e.preventDefault(); start() }}>
            <label className="block"><span className="mb-1 block font-medium">To</span>
              <Input list="ax-compose-contacts" type="email" required value={f.to} placeholder="name@example.com" autoFocus
                onChange={e => setF({ ...f, to: e.target.value })} disabled={busy} />
              <datalist id="ax-compose-contacts">{contacts.map(c => <option key={c.address} value={c.address}>{c.name}</option>)}</datalist>
              {known?.name && <span className="text-muted-foreground mt-1 block text-xs">{known.name}</span>}
            </label>
            <label className="block"><span className="mb-1 block font-medium">Topic</span>
              <Input required value={f.topic} maxLength={500} placeholder="e.g. the project update, or a quote for the new website" onChange={e => setF({ ...f, topic: e.target.value })} disabled={busy} /></label>
            <label className="block"><span className="mb-1 block font-medium">Target – what should the mail achieve?</span>
              <textarea required rows={2} className={area} value={f.target} maxLength={1000} placeholder="e.g. get a 30-min call next week, or an offer by Friday"
                onChange={e => setF({ ...f, target: e.target.value })} disabled={busy} /></label>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <label className="block"><span className="mb-1 block font-medium">Tone</span>
                <NativeSelect value={f.tone} onChange={e => setF({ ...f, tone: e.target.value })} disabled={busy}>
                  {TONES.map(t => <option key={t} value={t}>{t[0].toUpperCase() + t.slice(1)}</option>)}</NativeSelect></label>
              <label className="block"><span className="mb-1 block font-medium">Language</span>
                <NativeSelect value={f.language} onChange={e => setF({ ...f, language: e.target.value })} disabled={busy}>
                  {[['auto', 'Automatic'], ['Danish', 'Danish'], ['English', 'English'], ['German', 'German']].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</NativeSelect></label>
              <label className="block"><span className="mb-1 block font-medium">From</span>
                <NativeSelect value={f.account} onChange={e => setF({ ...f, account: e.target.value })} disabled={busy}>
                  {profile().accounts.map(a => <option key={a.id} value={a.id}>{a.label}{a.kind === 'private' ? ' (private)' : ''}</option>)}</NativeSelect></label>
            </div>
            <label className="block"><span className="mb-1 block font-medium">Facts to include <span className="text-muted-foreground font-normal">(optional)</span></span>
              <textarea rows={2} className={area} value={f.notes} maxLength={2000} placeholder="Dates, numbers, links – Axella won't invent any"
                onChange={e => setF({ ...f, notes: e.target.value })} disabled={busy} /></label>
            {!busy && st?.state === 'failed' && <div className="text-destructive flex items-start gap-1.5 text-xs"><AlertTriangle className="mt-px size-3.5 shrink-0" />Couldn't write the draft: {st.error}</div>}
            <div className="flex items-center justify-end gap-3">
              {busy && <span className="text-muted-foreground flex items-center gap-1.5 text-xs"><Loader2 className="size-3.5 animate-spin" />
                {st?.state === 'queued' && st.waiting_for ? `Waiting for “${st.waiting_for}” to finish…` : `Axella is writing… ${secs}s`}</span>}
              <Button type="submit" disabled={busy}><Sparkles />{busy ? 'Drafting…' : 'Draft it'}</Button>
            </div>
          </form>}

          {res && <div className="space-y-3">
            {res.context && <div className="text-muted-foreground text-xs">Built on: {res.context}</div>}
            {!!res.warnings?.length && <div className="bg-card rounded-md border px-3 py-2 text-xs">
              {res.warnings.map((w, i) => <div key={i} className="flex items-start gap-1.5"><AlertTriangle className="text-dawn mt-px size-3.5 shrink-0" />{w}</div>)}</div>}
            <div className="text-muted-foreground text-xs">To {res.name ? `${res.name} <${res.to}>` : res.to} · from {accLabel(res.account)}{res.language ? ' · ' + res.language : ''}</div>
            <label className="block"><span className="mb-1 block font-medium">Subject</span><Input value={subject} onChange={e => setSubject(e.target.value)} /></label>
            <ToggleGroup type="single" value={String(pick)} onValueChange={v => v && setPick(+v)}>
              {res.variants.map((v, i) => <ToggleGroupItem key={i} value={String(i)}>{v.label}</ToggleGroupItem>)}
            </ToggleGroup>
            <textarea rows={12} className={area + ' font-[inherit] leading-relaxed'} value={texts[pick] || ''}
              onChange={e => setTexts(t => t.map((x, i) => i === pick ? e.target.value : x))} />
            <div className="-mt-1 flex flex-wrap items-center gap-3 text-[13px]"><AttachButton onFiles={att.add} />
              {!!att.list.length && <span className="text-ink-3">Attachments go with Send, not with Save to Drafts</span>}</div>
            <div className="-mx-4"><AttachList list={att.list} onRemove={att.remove} /></div>
            <BasedOn ids={res.kb} />
            <form className="flex gap-2" onSubmit={e => { e.preventDefault(); if (!rework.trim()) return
              const draft = texts[pick]; setRes(null); setRework('')
              start({ draft, subject, instruction: rework.trim() }) }}>
              <Input value={rework} onChange={e => setRework(e.target.value)} placeholder="Rework: e.g. shorter, mention the invoice, more direct…" />
              <Button type="submit" variant="outline" disabled={!rework.trim()}><Wand2 />Rework</Button>
            </form>
            <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
              <Button variant="ghost" onClick={() => { setRes(null); setSt(null) }}><RotateCcw />Start over</Button>
              <Button variant="ghost" title="Keep facts from this mail for later drafts" onClick={() => openKnowledge({ title: subject, body: texts[pick],
                scope: 'overall', visibility: 'internal', category: profile().accounts.find(a => a.id === res.account)?.kind === 'work' ? 'employer' : 'private',
                source: { kind: 'manual', label: 'New mail to ' + (res.name || res.to) + ' – ' + subject, date: isoDate(new Date()) } })}><KnowledgeIcon />Save as knowledge</Button>
              <Button variant="outline" onClick={() => navigator.clipboard.writeText(texts[pick]).then(() => toast.success('Copied'))}><Copy />Copy</Button>
              <Button variant="outline" onClick={save} disabled={saving || !subject.trim()}>{saving ? <Loader2 className="animate-spin" /> : <Save />}Save to Drafts</Button>
              <SendLaterButton to={res.name || res.to} disabled={saving || !subject.trim() || !texts[pick]?.trim() || att.busy} onSchedule={later} />
              <SendButton size="default" to={(res.name || res.to).split(/\s+/)[0]} disabled={saving || !subject.trim() || !texts[pick]?.trim() || att.busy} onSend={() => send()} />
            </div>
          </div>}
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** One dialog for the whole app – opened from the menu (the phone menu closes itself, so it can't own the dialog). */
export const openCompose = (init?: ComposePrefill) => window.dispatchEvent(new CustomEvent('ax-compose', { detail: init || {} }))
export function ComposeHost() {
  const [open, setOpen] = useState<ComposePrefill | null>(null)
  useEffect(() => { const h = (e: Event) => setOpen((e as CustomEvent).detail || {}); window.addEventListener('ax-compose', h); return () => window.removeEventListener('ax-compose', h) }, [])
  return open ? <ComposeDialog init={open} onClose={() => setOpen(null)} /> : null
}
