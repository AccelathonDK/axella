import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Loader2, Lock, Mail, Paperclip, Search as SearchIcon, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ItemSheet } from '@/components/ItemSheet'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { archivePath, loadDigest } from '@/lib/data'
import { mdInline } from '@/lib/md'
import { accLabel } from '@/lib/profile'
import { CH_ICON, SEC } from '@/lib/sections'
import type { Item, Safety } from '@/lib/types'
import { cn } from '@/lib/utils'

/* Search: two sources, one list each.
   1. Axella's history – every item that has been in a digest (the full-text index on the Mac mini). Live while you type.
   2. All mail on the Mac mini – Spotlight over Apple Mail's files, including mail from before Axella. On Enter, or
      by itself when the history has nothing. Both open in the item sheet: message, photos, reply. */
interface Hit { digest: string; id: string; generated?: string; section: string; channel?: string; from_name?: string; from_address?: string; headline?: string; subject?: string; safety?: Safety }
interface Found { token: string | null; private?: boolean; subject: string; from_name?: string; from_address?: string; from_me?: boolean; to?: string; date?: string; message_id?: string | null; account?: string | null; mailbox?: string; has_attachments?: boolean; safety?: Safety }

const when = (iso?: string) => {
  const d = iso ? new Date(iso) : null
  if (!d || isNaN(+d)) return ''
  const now = new Date()
  return d.toLocaleDateString('en-GB', d.getFullYear() === now.getFullYear() ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' })
}

export function SearchView({ q0 = '' }: { q0?: string }) {
  const { ax } = useApp()
  const [q, setQ] = useState(q0)
  const [hits, setHits] = useState<Hit[] | null>(null)
  const [mail, setMail] = useState<{ q: string; items: Found[]; error?: string; limit?: number } | null>(null)
  const [mailBusy, setMailBusy] = useState(false)
  const [open, setOpen] = useState<Item | null>(null)
  const [opening, setOpening] = useState<string | null>(null)
  const seq = useRef(0)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {                                     // the query lives in the URL, so Back and reload keep it
    const u = new URL(location.href); if (q.trim()) u.searchParams.set('q', q.trim()); else u.searchParams.delete('q'); history.replaceState(null, '', u)
  }, [q])

  useEffect(() => {                                     // history: live, debounced
    const s = q.trim()
    if (s.length < 2 || !ax.apiOk) { setHits(null); return }
    const n = ++seq.current
    const t = setTimeout(() => get<{ items: Hit[] }>('search?q=' + encodeURIComponent(s))
      .then(j => { if (n === seq.current) setHits(j.items || []) }).catch(() => { if (n === seq.current) setHits([]) }), 250)
    return () => clearTimeout(t)
  }, [q, ax.apiOk])

  const searchMail = async (s = q.trim(), limit = 40) => {
    if (s.length < 2 || mailBusy) return
    setMailBusy(true)
    try { const j = await get<{ items: Found[]; error?: string }>('mail_search?q=' + encodeURIComponent(s) + '&limit=' + limit); setMail({ q: s, items: j.items || [], error: j.error, limit }) }
    catch (e: any) { setMail({ q: s, items: [], error: e.message }) }
    finally { setMailBusy(false) }
  }
  // nothing in the history → look in all mail by itself (once per query)
  useEffect(() => { const s = q.trim(); if (hits && !hits.length && s.length >= 2 && mail?.q !== s) searchMail(s) }, [hits])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (q0.trim().length >= 2) searchMail(q0.trim()) }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const openHit = async (h: Hit) => {
    setOpening(h.digest + h.id)
    try {
      const name = h.digest.endsWith('.md') ? h.digest : h.digest + '.md'
      const d = await loadDigest(name).catch(() => loadDigest(archivePath(name)))
      const it = d.items.find(i => String(i.id) === h.id)
      if (!it) throw new Error('not in that digest any more')
      setOpen(it)
    } catch (e: any) { toast.error("Couldn't open it: " + e.message) } finally { setOpening(null) }
  }
  const openFound = (f: Found) => setOpen({
    id: 'found:' + (f.message_id || f.token), section: 'open', channel: 'mail', account: f.account || undefined, message_id: f.message_id || undefined,
    subject: f.subject, headline: f.subject, from: { name: f.from_name || undefined, address: f.from_address || undefined },
    safety: f.safety, found: f.token || undefined, found_in: [f.account ? accLabel(f.account) : '', f.mailbox].filter(Boolean).join(' / '), date: f.date,
  })

  const s = q.trim()
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><SearchIcon className="size-5" />Search</h1>
        <p className="text-muted-foreground text-sm">Everything Axella has shown you, and all mail on the Mac mini. Nothing is changed or marked as read.</p>
      </div>
      <form className="relative" onSubmit={e => { e.preventDefault(); searchMail() }}>
        <SearchIcon className="text-ink-3 pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
        <Input ref={input} autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Name, address, subject or words in the mail…" enterKeyHint="search"
          aria-label="Search" className="h-11 pr-10 pl-9 text-[16px]" />
        {q && <button type="button" aria-label="Clear" onClick={() => { setQ(''); setMail(null); input.current?.focus() }}
          className="text-ink-3 hover:text-ink absolute top-1/2 right-2 -translate-y-1/2 rounded p-1.5"><X className="size-4" /></button>}
      </form>

      {!ax.apiOk && <div className="text-ink-3 text-sm">Search needs the Mac mini – it isn't answering right now.</div>}

      {s.length >= 2 && ax.apiOk && <section>
        <div className="ax-label mb-2 flex items-center gap-2">In Axella<span className="text-ink-3 normal-case tracking-normal">{hits ? hits.length + (hits.length === 50 ? '+' : '') : ''}</span></div>
        {!hits ? <Loading /> : !hits.length ? <div className="text-ink-3 text-sm">Nothing in your digests.</div>
          : <ul className="bg-card divide-y rounded-lg border">{hits.map(h => {
            const I = (h.channel && CH_ICON[h.channel]) || Mail
            return <li key={h.digest + h.id}><button onClick={() => openHit(h)} className="hover:bg-bg-2 flex w-full items-start gap-3 px-4 py-3 text-left">
              <I className="text-ink-3 mt-0.5 size-4 shrink-0" />
              <span className="min-w-0 flex-1">
                <span className="md-inline block truncate font-medium" dangerouslySetInnerHTML={{ __html: mdInline(h.headline || h.subject || '(no title)') }} />
                <span className="text-ink-3 block truncate text-[13px]">{h.safety && <span className="text-ink mr-1.5 font-medium">{h.safety.label} ·</span>}{[h.from_name || h.from_address, SEC[h.section as keyof typeof SEC]?.short].filter(Boolean).join(' · ')}</span>
              </span>
              <span className="text-ink-3 shrink-0 font-mono text-[12px]">{opening === h.digest + h.id ? <Loader2 className="size-4 animate-spin" /> : when(h.generated)}</span>
            </button></li>
          })}</ul>}
      </section>}

      {s.length >= 2 && ax.apiOk && <section>
        <div className="mb-2 flex items-center gap-2">
          <span className="ax-label">All mail</span>
          {mail?.q === s && !mailBusy && <span className="text-ink-3 text-xs">{mail.items.length}{mail.items.length >= (mail.limit || 40) ? `+ – the newest ${mail.items.length}` : ''}</span>}
          {!(mail?.q === s) && !mailBusy && <Button size="sm" variant="outline" className="ml-auto" onClick={() => searchMail()}><SearchIcon />Search all mail</Button>}
        </div>
        {mailBusy ? <Loading text="Searching all mail on the Mac mini…" />
          : mail?.q !== s ? <div className="text-ink-3 text-sm">Press Enter or “Search all mail” to look through every mail on the Mac mini, including mail from before Axella – all your mailboxes, whatever the Work/Private filter at the top says.</div>
          : mail.error ? <div className="text-destructive text-sm">{mail.error}</div>
          : !mail.items.length ? <div className="text-ink-3 text-sm">No mail found. Spotlight searches whole words and the start of words – try fewer or shorter words.</div>
          : <ul className="bg-card divide-y rounded-lg border">{mail.items.map((f, i) => f.private
            // a private contact: who and when only – the mail itself stays in Mail
            ? <li key={'p' + i} className="flex items-start gap-3 px-4 py-3">
              <Lock className="text-ink-3 mt-0.5 size-4 shrink-0" />
              <span className="min-w-0 flex-1"><span className="block truncate font-medium">{f.from_name}</span>
                <span className="text-ink-3 block text-[13px]">Private contact – not shown in Axella{f.account ? ' · ' + accLabel(f.account) : ''}</span></span>
              <span className="text-ink-3 shrink-0 font-mono text-[12px]">{when(f.date)}</span></li>
            : <li key={f.token || i}><button onClick={() => openFound(f)} className="hover:bg-bg-2 flex w-full items-start gap-3 px-4 py-3 text-left">
              <Mail className="text-ink-3 mt-0.5 size-4 shrink-0" />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{f.safety && <span className="text-ink-3 mr-1.5 text-[13px] font-normal">{f.safety.label} ·</span>}{f.subject}</span>
                <span className="text-ink-3 block truncate text-[13px]">{f.from_me ? 'You → ' + (f.to || '').replace(/\s*<[^>]*>/g, '') : (f.from_name || f.from_address)}{f.mailbox ? ' · ' + [f.account && accLabel(f.account), f.mailbox].filter(Boolean).join(' / ') : ''}</span>
              </span>
              <span className="text-ink-3 flex shrink-0 items-center gap-1.5 font-mono text-[12px]">{f.has_attachments && <Paperclip className="size-3.5" />}{when(f.date)}</span>
            </button></li>)}</ul>}
        {mail?.q === s && !mailBusy && !mail.error && mail.items.length >= (mail.limit || 40) && (mail.limit || 40) < 200 &&
          <Button size="sm" variant="outline" className="mt-2" onClick={() => searchMail(s, Math.min(200, (mail.limit || 40) * 3))}>Show more</Button>}
      </section>}

      {open && <ItemSheet it={open} handled={!open.found && ax.isHandled(open.id)} onClose={() => setOpen(null)}
        onCal={() => { setOpen(null); toast('Add it to the calendar from the item in its digest') }} />}
    </div>
  )
}

const Loading = ({ text = 'Searching…' }: { text?: string }) =>
  <div className={cn('text-ink-3 flex items-center gap-2 text-sm')}><Loader2 className="size-4 animate-spin" />{text}</div>
