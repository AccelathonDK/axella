import type { Call, CalEvent, Ctx, DigestData, DigestMeta, Item, Overrides, SectionKey } from './types'
import { calendarFor, isWorkAccount } from '@/lib/profile'
import { IOS, isoDate, pad } from './utils'

export const DIGEST_RE = /^\d{4}-\d{2}-\d{2}-\d{4}.*\.md$/

export async function listDir(dir: string): Promise<string[]> {
  const html = await (await fetch(dir, { cache: 'no-store' })).text()
  return [...new DOMParser().parseFromString(html, 'text/html').querySelectorAll('a')]
    .map(a => decodeURIComponent(a.getAttribute('href') || '').split('/').pop() || '')
}
export const digestNames = (files: string[]) => [...new Set(files.filter(n => DIGEST_RE.test(n)))].sort().reverse()

export function parseName(n: string): DigestMeta {
  const m = baseName(n).match(/^(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(?:-(\w+))?/)
  if (!m) return { label: n }
  const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5])
  const day = d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
  const kind = ({ p0: 'P0 alert', week: 'Week ahead' } as Record<string, string>)[m[6]] || 'Digest'
  return { date: d, kind, label: `${day} ${m[4]}:${m[5]}${m[6] ? ' · ' + kind : ''}` }
}

export const SECTION_TEST: [SectionKey, RegExp][] = [
  ['p0', /^P0/i], ['p1', /^P1/i], ['p2', /^P2/i], ['open', /still open|open from/i], ['p3', /^P3|FYI/i],
  ['cal', /calendar/i], ['wait', /waiting/i], ['file', /filing/i],
]

/** name is relative to digests/, e.g. "2026-10-28-0730.md" or "archive/2026-09/2026-09-01-0730.md" */
export async function loadDigest(name: string): Promise<DigestData> {
  const url = 'digests/' + name.split('/').map(encodeURIComponent).join('/')
  const j = await fetch(url.replace(/\.md$/, '.json'), { cache: 'no-store' })
  if (j.ok) {
    try {
      const data = await j.json()
      data.items = (data.items || []).filter((i: Item) => i && i.section)
      return data
    } catch { /* half-written sidecar – a run is still writing it; fall back for now, the caller retries */ }
  }
  const m = await fetch(url, { cache: 'no-store' })
  if (!m.ok) throw new Error('digest not found')
  // read-only fallback: very old digests have no .json – and a brand-new one can show its .md a moment before its .json
  return { ...mdToData(await m.text()), fromMd: true }
}
export const baseName = (n: string) => n.split('/').pop() || n
export const isRegular = (n: string) => !/-p0\b/.test(baseName(n))          // P0 alerts stay out of the picker
export const archivePath = (n: string) => `archive/${n.slice(0, 7)}/${n}`
export const dayKey = (n: string) => baseName(n).slice(0, 10)
export function dayLabel(key: string) {
  const d = new Date(key + 'T00:00'), t = new Date(); t.setHours(0, 0, 0, 0)
  const diff = Math.round((t.getTime() - d.getTime()) / 864e5)
  return diff === 0 ? 'Today' : diff === 1 ? 'Yesterday' : d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}
/** sub-folders (and files) of a directory listing, as raw names */
export async function listEntries(dir: string): Promise<string[]> {
  const r = await fetch(dir, { cache: 'no-store' })
  if (!r.ok) return []
  return [...new DOMParser().parseFromString(await r.text(), 'text/html').querySelectorAll('a')].map(a => decodeURIComponent(a.getAttribute('href') || ''))
}

/* Older digests without a .json sidecar */
export function mdToData(text: string): DigestData {
  const out: DigestData = { intro: '', spoken: '', items: [] }
  let cur: (Item & { raw: string[] }) | null = null, sec: string | null = null, n = 0
  const intro: string[] = []
  for (const l of text.split('\n')) {
    if (/^# /.test(l)) continue
    if (/^## /.test(l)) { const h = l.slice(3).trim(); sec = /spoken/i.test(h) ? 'spoken' : SECTION_TEST.find(([, re]) => re.test(h))?.[0] || null; cur = null; continue }
    if (sec === 'spoken') { out.spoken += ' ' + l.trim(); continue }
    if (!sec) { if (l.trim()) intro.push(l.trim()); continue }
    if (/^[-*] /.test(l)) { cur = { id: 'md-' + n++, section: sec as SectionKey, raw: [l.slice(2)] }; out.items.push(cur) }
    else if (cur && /^\s+\S/.test(l)) cur.raw.push(l.trim())
    else if (l.trim() && !/^(none|nothing)\b/i.test(l.trim())) { cur = { id: 'md-' + n++, section: sec as SectionKey, raw: [l.trim()] }; out.items.push(cur) }
  }
  out.intro = intro.join(' ')
  for (const it of out.items as (Item & { raw?: string[] })[]) {
    let t = (it.raw || []).join('\n'), draft = ''
    const dm = t.match(/Suggested draft:?([\s\S]*)$/i); if (dm) { draft = dm[1].trim(); t = t.slice(0, dm.index).trim() }
    const bm = t.match(/^\*\*(.+?)\*\*\.?\s*([\s\S]*)$/), cm = t.match(/^([^:\n]{3,60}):\s+([\s\S]*)$/)
    if (bm) { it.headline = bm[1]; it.detail = bm[2] } else if (cm) { it.headline = cm[1]; it.detail = cm[2] } else it.detail = t
    if (draft) it.draft = { mode: 'copy', text: draft }
    it.readonly = true; delete it.raw
  }
  out.spoken = (out.spoken || '').trim()
  return out
}

/* Work/private per schedule: which worlds a digest covers (missing = both) */
export const digestScope = (d?: DigestData | null): ('work' | 'private')[] => {
  const s = (d?.scope || []).filter(x => x === 'work' || x === 'private')
  return s.length ? [...new Set(s)].sort() as ('work' | 'private')[] : ['private', 'work']
}
export const scopeLabel = (w: string[]) => w.length === 1 ? (w[0] === 'work' ? 'Work' : 'Private') : ''

/* Work / private */
/* Fallback only – digests set "context" themselves (rules in AXELLA.md "Work / private"); this catches items without it.
   Kept generic on purpose: your own employer/client names live in AXELLA.md, not in the code. */
export const WORK_RE = /\bwork\b|jira|confluence|atlassian|github|gitlab|bitbucket/i
export const senderKey = (x: Item | Call) => (x.from?.address || x.from?.number || '').trim().toLowerCase().replace(/\s/g, '')
export function ctxOf(x: Item | Call, o: Overrides): Ctx {
  const sk = senderKey(x), dom = sk.includes('@') ? sk.split('@')[1] : ''
  const id = String(x.id).toLowerCase()
  if (o.item?.[id]) return o.item[id]
  if (sk && o.sender?.[sk]) return o.sender[sk]
  if (dom && o.domain?.[dom]) return o.domain[dom]
  if (x.context === 'work' || x.context === 'private') return x.context
  const it = x as Item
  if (isWorkAccount(it.account)) return 'work'
  const hay = [x.context, it.headline, it.detail, it.subject, it.file_to, x.from?.name, x.from?.address, x.summary].filter(Boolean).join(' ')
  return WORK_RE.test(hay) ? 'work' : 'private'
}

/* Reply links (nothing is ever sent – these open the right app with the draft) */
/* WhatsApp: the app's own link (Mac/Windows/iPhone/iPad/Android app) – wa.me only as the web fallback in ⋯ */
/* A WhatsApp group has an id like 120363…@g.us, not a phone number – no link opens a group, so the reply opens
   WhatsApp's "send to…" picker with the text (and it's copied too, in case the app only opens) */
const waGroup = (a?: string) => !!a && (/@g\.us$/i.test(a) || a.replace(/[^\d]/g, '').length > 15)
const waNum = (a?: string) => (a || '').replace(/@.*$/, '').replace(/[^\d]/g, '')
/** Senders nobody can answer: noreply@…, no-reply@…, donotreply@…, mailer-daemon@… */
// "noreply@…", but also "payments-noreply@…", "no_reply.billing@…", "donotreply@…", "bounces+123@…" (anywhere in the
// part before @, as its own word). Mirrored in setup/axella-actions.py (NO_REPLY) so Send is refused there too.
export const NO_REPLY = /^(?:[^@]*[-+._])?(no-?reply|no_reply|do-?not-?reply|do_not_reply|mailer-daemon|postmaster|bounces?|notifications?)(?:[-+._][^@]*)?@/i
export const isNoReply = (a?: string) => NO_REPLY.test((a || '').trim())
/** Machines, not people: no-reply addresses and the usual automated and invoicing mailboxes (invoice@, billing@,
    faktura@, receipts@, alerts@, newsletter@ …) – never offered as a VIP. */
const AUTOMATED_LOCAL = /^(?:[^@]*[-+._])?(invoices?|billing|faktura|fakturering|regning(er)?|receipts?|kvittering(er)?|payments?|betaling|alerts?|news(letter)?|nyhedsbrev|updates?|mailer|system|automated|auto|marketing)(?:[-+._][^@]*)?@/i
export const isAutomatedSender = (a?: string) => isNoReply(a) || AUTOMATED_LOCAL.test((a || '').trim())

export function replyLink(it: Item): { href: string; label: string; kind: string; web?: string; copy?: string } | null {
  if (it.channel === 'linkedin') return { href: it.deep_link && /^https:\/\/www\.linkedin\.com\//.test(it.deep_link) ? it.deep_link : 'https://www.linkedin.com/messaging/', label: 'Reply on LinkedIn', kind: 'linkedin' }
  const d = it.draft, ch = it.channel || 'mail'
  if (!d?.text) {
    // no draft: still offer to jump straight into the conversation
    if (ch === 'whatsapp' && waGroup(it.from?.address)) return { href: 'whatsapp://', label: 'Open WhatsApp', kind: 'whatsapp' }
    const num = (it.from?.number || (/^\+?[\d\s-]{6,}$/.test(it.from?.address || '') ? it.from!.address! : '')).replace(/[^\d+]/g, '')
    if (ch === 'whatsapp' && num) { const n = num.replace('+', ''); return { href: `whatsapp://send?phone=${n}`, web: `https://wa.me/${n}`, label: 'Open chat', kind: 'whatsapp' } }
    if ((ch === 'imessage' || ch === 'sms') && num) return { href: `sms:${encodeURIComponent(num)}`, label: 'Open chat', kind: 'sms' }
    if (ch === 'signal') return { href: num ? `sgnl://signal.me/#p/${num.startsWith('+') ? num : '+' + num}` : 'sgnl://', label: num ? 'Open chat' : 'Open Signal', kind: 'signal' }
    return null
  }
  const addr = (d.to || it.from?.address || it.from?.number || '').trim(), text = d.text
  if (ch === 'whatsapp' && waGroup(addr)) return { href: `whatsapp://send?text=${encodeURIComponent(text)}`, label: 'Reply in WhatsApp', kind: 'whatsapp', copy: text }
  if (ch === 'whatsapp') { const num = waNum(addr), t = encodeURIComponent(text); return { href: num ? `whatsapp://send?phone=${num}&text=${t}` : `whatsapp://send?text=${t}`, web: num ? `https://wa.me/${num}?text=${t}` : undefined, label: 'Reply in WhatsApp', kind: 'whatsapp' } }
  if (ch === 'signal') {   // Signal links can't carry text: open the chat and copy the reply
    const num = (it.from?.number || addr).replace(/[^\d+]/g, '')
    return { href: /^\+?\d{6,}$/.test(num) ? `sgnl://signal.me/#p/${num.startsWith('+') ? num : '+' + num}` : 'sgnl://', label: 'Reply in Signal', kind: 'signal', copy: text }
  }
  if (ch === 'imessage' || ch === 'sms') return { href: `sms:${encodeURIComponent(addr)}${IOS ? '&' : '?'}body=${encodeURIComponent(text)}`, label: 'Reply in Messages', kind: 'sms' }
  if (ch === 'mail') {
    let subj = d.subject || it.subject || ''
    if (d.mode === 'reply' && subj && !/^re:/i.test(subj)) subj = 'Re: ' + subj
    return { href: `mailto:${encodeURIComponent(addr)}?subject=${encodeURIComponent(subj)}&body=${encodeURIComponent(text)}`, label: 'New mail', kind: 'mail' }
  }
  return null
}

export { cals, calLabel } from '@/lib/profile'

export function guessEvent(it: Item, o: Overrides): CalEvent & { guessed: boolean } {
  if (it.event) return { ...it.event, guessed: false }
  const txt = (it.headline || '') + ' ' + (it.detail || '')
  const M: Record<string, number> = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, maj: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, okt: 9, nov: 10, dec: 11 }
  const now = new Date(); let d = new Date(now)
  const dm = txt.match(/(\d{1,2})\.?\s*(jan|feb|mar|apr|maj|may|jun|jul|aug|sep|okt|oct|nov|dec)/i)
  if (dm) { d = new Date(now.getFullYear(), M[dm[2].toLowerCase()], +dm[1]); if (d < new Date(now.getFullYear(), now.getMonth(), now.getDate())) d.setFullYear(d.getFullYear() + 1) }
  else if (/tomorrow|i morgen/i.test(txt)) d.setDate(d.getDate() + 1)
  const tm = txt.match(/(\d{1,2})[:.](\d{2})\s*[–-]\s*(\d{1,2})[:.](\d{2})/) || txt.match(/(\d{1,2})[:.](\d{2})/)
  const ds = isoDate(d)
  const sh = tm ? +tm[1] : Math.min(now.getHours() + 1, 22), sm = tm ? +tm[2] : 0
  const eh = tm && tm[3] ? +tm[3] : sh + 1, em = tm && tm[4] ? +tm[4] : sm
  const title = (it.headline || '').replace(/^(today|rest of today|\w{3} \d{1,2} \w{3})\s*[~]?[\d:.]*\s*[–-]\s*/i, '').trim() || 'Event'
  return {
    calendar: calendarFor(ctxOf(it, o) === 'work', it.account, txt),
    title, start: `${ds}T${pad(sh)}:${pad(sm)}`, end: `${ds}T${pad(Math.min(eh, 23))}:${pad(em)}`, location: '', guessed: true,
  }
}

/** A task's Work / Private is optional: unset, it shows under both filters (and under All). */
export const taskInCtx = (t: { ctx?: string | null }, ctx: string) => ctx === 'all' || !t.ctx || t.ctx === ctx
