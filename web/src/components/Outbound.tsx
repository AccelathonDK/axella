/* Settings → Privacy → What leaves my home: everything that went out of the Mac mini in the last 7 days, from the
   records Axella keeps anyway – Claude runs, the briefings' web searches and pages, mail you sent, the call agent,
   notifications, problem reports. Counts, times, search queries and web addresses only (GET outbound). */
import { useEffect, useState } from 'react'
import { ArrowUpRight, ChevronDown, ChevronRight } from '@/components/ax-icons'
import { SectionCard } from '@/components/Section'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'

interface Out {
  days: number; since: string
  claude: { runs: number; by: { what: string; count: number; failed?: number }[]; capped?: boolean; history_from?: string | null }
  web: { briefs: { name: string; at: string; queries: string[]; urls: string[]; fetched: number }[]; queries: number; pages: number }
  mail: { sent: number; sms: number; forwarded: number; forwarded_auto?: number; unsubscribed: number }
  voice: { contacts_sent?: number | null; config_pushed?: string | null; lookup?: string | null; private?: number | null; calls_fetched: number; last_sync?: string | null } | null
  signal?: { linked: boolean }
  push: { devices: number; discreet: boolean }
  reports: { sent: number }
  pictures: { senders: number; fetched?: number }
  meetings?: { pages: number; assist: number }
  notes?: { read: number; asks: number }
}

const when = (iso?: string | null) => iso ? new Date(iso).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''
const plural = (n: number, one: string, many = one + 's') => `${n} ${n === 1 ? one : many}`
const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, '') } catch { return u } }

export function OutboundCard() {
  const { ax } = useApp()
  const [d, setD] = useState<Out | null>(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState<number | null>(null)
  useEffect(() => { if (ax.apiOk) get<Out>('outbound').then(setD).catch(e => setErr(e.message)) }, [ax.apiOk])
  if (!ax.apiOk) return null
  return <SectionCard id="outbound" icon={ArrowUpRight} title="What leaves my home" sub={d ? `The last ${d.days} days – where your data went from the Mac mini` : 'Loading…'}>
    {err ? <div className="text-dawn p-4 text-sm">{err}</div> : d && <div className="divide-y text-sm" data-outbound="">
      <Row title="Claude (Anthropic)" value={`${d.claude.runs}${d.claude.capped ? '+' : ''} ${d.claude.runs === 1 && !d.claude.capped ? 'run' : 'runs'}${d.claude.history_from ? ' since ' + new Date(d.claude.history_from).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : ''}`}
        note="Each digest, check and question sends what that run reads – your mail, messages and calls from Normal contacts – to Claude to be answered. Private and Hidden contacts are taken out first, on the Mac mini.">
        {d.claude.by.length > 0 && <ul className="text-ink-2 mt-1 text-[13px]">{d.claude.by.map(b => <li key={b.what}>{b.what}: {b.failed === undefined ? plural(b.count, 'request') : plural(b.count, 'run') + (b.failed ? ` (${b.failed} failed)` : '')}</li>)}</ul>}
      </Row>
      <Row title="The web (briefings)" value={d.web.briefs.length ? `${plural(d.web.queries, 'search', 'searches')} · ${plural(d.web.pages, 'page')}` : 'nothing'}
        note="Briefing runs search the web and read pages through Claude's web search. Only the topic you set goes out – never your mail or messages. The list comes from the runs' actual tool calls.">
        {d.web.briefs.length > 0 && <ul className="mt-1.5 space-y-1">{d.web.briefs.map((b, i) => <li key={i}>
          <button type="button" onClick={() => setOpen(open === i ? null : i)} className="text-ink-2 hover:text-ink flex w-full items-center gap-1.5 text-left text-[13px]">
            {open === i ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            <span className="font-medium">{b.name}</span><span className="text-ink-3">{when(b.at)} · {plural(b.queries.length, 'search', 'searches')}, {plural(b.fetched, 'page')}</span></button>
          {open === i && <div className="text-ink-2 mt-1 ml-5 space-y-1 text-[12.5px]" data-outbound-brief="">
            {b.queries.map((q, j) => <div key={'q' + j}>Searched: <span className="font-mono">{q}</span></div>)}
            {b.urls.map((u, j) => <div key={'u' + j} className="truncate">Read: {/^https?:\/\//i.test(u)
              ? <><a href={u} target="_blank" rel="noreferrer noopener" className="hover:underline">{host(u)}</a> <span className="text-ink-3">{u.replace(/^https?:\/\/(www\.)?[^/]+/, '').slice(0, 80)}</span></>
              : <span className="text-ink-3">{u.slice(0, 80)}</span>}</div>)}
            {!b.queries.length && !b.urls.length && <div className="text-ink-3">No searches recorded for this run.</div>}
          </div>}
        </li>)}</ul>}
      </Row>
      <Row title="Mail you sent" value={plural(d.mail.sent, 'reply', 'replies')}
        note="Only when you tapped Send – sent through Apple Mail like any other mail. Never by a run or on a schedule.">
        {(d.mail.forwarded > 0 || d.mail.unsubscribed > 0 || d.mail.sms > 0) && <div className="text-ink-2 mt-1 text-[13px]">
          {[d.mail.forwarded && `${plural(d.mail.forwarded, 'receipt')} forwarded to your bookkeeping${d.mail.forwarded_auto ? ` (${d.mail.forwarded_auto} automatically)` : ''}`, d.mail.unsubscribed && `${d.mail.unsubscribed} unsubscribed`, d.mail.sms && plural(d.mail.sms, 'text message')].filter(Boolean).join(' · ')}</div>}
      </Row>
      {d.voice && <Row title="Call agent (Vercel)" value={plural(d.voice.calls_fetched, 'call') + ' collected'}
        note={`Every 6 hours the Mac mini sends the call agent your greeting and your contacts${d.voice.lookup === 'hashed' ? ' – each one\'s first name and a one-way code of the number, never full names or numbers' : ' – names and numbers'}. Hidden contacts are left out; Private ones are marked so the agent doesn't use AI with them${d.voice.private ? ` (${d.voice.private} marked)` : ''}. Calls are fetched and then deleted there.`}>
        <div className="text-ink-3 mt-1 text-[12.5px]">{[d.voice.contacts_sent != null && plural(d.voice.contacts_sent, 'contact') + ' known to the agent', d.voice.config_pushed && 'last sent ' + when(d.voice.config_pushed)].filter(Boolean).join(' · ')}</div>
      </Row>}
      <Row title="Notifications" value={plural(d.push.devices, 'device')}
        note={`Sent encrypted through Apple's or Google's push service to your own devices.${d.push.discreet ? ' Names are left out (discreet notifications).' : ' They show the sender and a short line.'}`} />
      <Row title="Problem reports" value={d.reports.sent ? plural(d.reports.sent, 'report') + ' sent' : 'none sent'}
        note="Only when you press Send on a report – you see exactly what goes before it leaves." />
      {(d.pictures.senders > 0 || !!d.pictures.fetched) && <Row title="Pictures in mail" value={plural(d.pictures.fetched || 0, 'picture') + ' loaded'}
        note={`Remote pictures load only when you tap Load pictures, or for the ${plural(d.pictures.senders, 'sender')} you always allow. Each one is fetched from your home connection, which tells that sender's server the mail was opened.`} />}
      {!!(d.meetings?.pages || d.meetings?.assist) && <Row title="Meeting prep" value={[d.meetings.pages && plural(d.meetings.pages, 'web page') + ' fetched', d.meetings.assist && plural(d.meetings.assist, 'assistant request')].filter(Boolean).join(' · ')}
        note="A web page is fetched once when you add it to a prep. The assistant sends that prep, its material and the context Axella gathered to Claude – only when you tap it, without private contacts or protected-workplace content." />}
      {!!d.notes?.read && <Row title="Your notes" value={`Ask Axella read ${plural(d.notes.read, 'note')}` + (d.notes.asks > 1 ? ` in ${d.notes.asks} questions` : '')}
        note="Only Ask Axella reads notes, and only when you ask it something – never a note linked to a private contact. Digests, drafts and the assistant never read them." />}
      {d.signal?.linked && <Row title="Signal" value="delivery receipts"
        note="The Mac mini is a linked Signal device: like your phone, it confirms to Signal that messages were delivered. Nothing else is sent." />}
      <p className="text-ink-3 px-4 py-3 text-[12px] leading-snug">Not Axella's doing and not listed: Apple Mail, Messages and WhatsApp syncing with their own servers, Tailscale, and macOS itself.</p>
    </div>}
  </SectionCard>
}

function Row({ title, value, note, children }: { title: string; value: string; note: string; children?: React.ReactNode }) {
  return <div className="px-4 py-3">
    <div className="flex items-baseline gap-2"><span className="font-medium">{title}</span><span className="text-ink-2 ml-auto shrink-0 text-[13px]">{value}</span></div>
    <p className="text-ink-3 mt-0.5 text-[12.5px] leading-snug">{note}</p>
    {children}
  </div>
}
