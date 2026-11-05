/* Contacts (sidebar) and New › Message: your address book from the Mac mini (GET contacts – macOS Contacts plus people
   you mail with), searchable, with Favourites on top like the iPhone's. Favourites are the VIPs (contacts.md) – star
   one here and it is a VIP everywhere. A contact opens a card with what you can do: Message (Messages), Mail (the
   composer, or Mail itself for a private contact), WhatsApp, Signal and Call. Nothing is sent from here – each opens
   the app on the device you're holding. Hidden contacts never appear; Private ones get no AI. */
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Mail, MessageCircle, Pencil, Phone, Plus, Search as SearchIcon, Star, Trash2, UserCircle, X } from '@/components/ax-icons'
import { openCompose } from '@/components/Compose'
import { KeepInTouchList } from '@/components/People'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input, NativeSelect } from '@/components/ui/input'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { loadVips } from '@/lib/vips'
import { IOS, cn } from '@/lib/utils'

/** Do it after 6 s unless Undo is tapped – for deletes (the Mac mini also keeps a copy for 90 days). */
export function withUndo(what: string, run: () => void) {
  let undone = false
  const t = setTimeout(() => { if (!undone) run() }, 6000)
  toast(what, { duration: 6000, action: { label: 'Undo', onClick: () => { undone = true; clearTimeout(t); toast('Not deleted') } } })
}

export interface Person { name: string; phones: string[]; emails: string[]; vip?: boolean; private?: boolean; source?: string
  id?: string; first?: string; last?: string; company?: string; phone_labels?: string[]; email_labels?: string[]
  /** 'YYYY-MM-DD', or '--MM-DD' without a year (from Contacts) */
  birthday?: string; birthday_shown?: boolean
  /** keep in touch (people.py): every 14, 30 or 91 days */
  keep?: number
  /** addresses you mail with under this contact's name that aren't on the card in Contacts */
  mail_only?: string[] }
interface Book { people: Person[]; at?: number | null; refreshing?: boolean; from_contacts?: boolean; owner?: boolean }

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
/** '1984-03-07' → '7 March 1984', '--03-07' → '7 March' */
export function bdayLabel(b?: string) {
  const m = /^(\d{4}|-)-(\d{2})-(\d{2})$/.exec(b || '')
  return m ? `${+m[3]} ${MONTHS[+m[2] - 1]}${m[1] !== '-' ? ' ' + m[1] : ''}` : ''
}

let cache: Book | null = null
const subs = new Set<(b: Book) => void>()
function load(refresh = false) {
  return get<Book>('contacts' + (refresh ? '?refresh=1' : '')).then(b => { cache = b; subs.forEach(f => f(b)); return b })
}
function useBook() {
  const [b, setB] = useState<Book | null>(cache)
  const [err, setErr] = useState('')
  useEffect(() => {
    subs.add(setB)
    load().catch(e => setErr(e.message))
    return () => { subs.delete(setB) }
  }, [])
  // a first read of Contacts runs in the background on the Mac mini: look again until it's there
  useEffect(() => {
    if (!b?.refreshing) return
    const t = setTimeout(() => load().catch(() => {}), 4000)
    return () => clearTimeout(t)
  }, [b])
  return { book: b, err }
}

const fold = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
function match(p: Person, q: string) {
  if (!q) return true
  const f = fold(q), d = q.replace(/[^\d]/g, '')
  return fold(p.name).split(/\s+/).some(w => w.startsWith(f)) || fold(p.name).includes(f)
    || p.emails.some(e => e.includes(f)) || (p.mail_only || []).some(e => e.includes(f)) || (d.length >= 3 && p.phones.some(x => x.replace(/\D/g, '').includes(d)))
}
const initials = (n: string) => n.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase()
const pretty = (p: string) => p.startsWith('+45') && p.length === 11 ? '+45 ' + p.slice(3).replace(/(\d{2})(?=\d)/g, '$1 ') : p

/* the links that open each app – on the iPhone, iPad or Mac you're using */
export const links = {
  sms: (n: string) => 'sms:' + n,
  whatsapp: (n: string) => 'whatsapp://send?phone=' + n.replace(/\D/g, ''),
  whatsappWeb: (n: string) => 'https://wa.me/' + n.replace(/\D/g, ''),
  signal: (n: string) => 'sgnl://signal.me/#p/' + n,
  tel: (n: string) => 'tel:' + n,
  mailto: (e: string) => 'mailto:' + e,
}

function Avatar({ p, size = 'md' }: { p: Person; size?: 'md' | 'lg' }) {
  return <span className={cn('bg-fjord-soft text-fjord inline-flex shrink-0 items-center justify-center rounded-full font-semibold',
    size === 'lg' ? 'size-16 text-xl' : 'size-9 text-[13px]')} aria-hidden>{initials(p.name) || <UserCircle className="size-5" />}</span>
}

function Row({ p, onOpen }: { p: Person; onOpen: (p: Person) => void }) {
  return <button type="button" onClick={() => onOpen(p)} className="hover:bg-bg-2 flex min-h-12 w-full items-center gap-3 px-4 py-2 text-left" data-contact="">
    <Avatar p={p} />
    <span className="min-w-0 flex-1">
      <span className="block truncate font-medium">{p.name}{p.vip && <Star className="text-dawn ml-1.5 inline size-3.5 align-[-2px]" aria-label="Favourite" />}</span>
      <span className="text-ink-3 block truncate text-[13px]">{p.phones[0] ? pretty(p.phones[0]) : p.emails[0] || p.mail_only?.[0]}{p.private && ' · private'}</span>
    </span>
  </button>
}

/** Search + Favourites + everyone A–Z. onOpen: what tapping a contact does. */
function ContactList({ onOpen, autoFocus }: { onOpen: (p: Person) => void; autoFocus?: boolean }) {
  const { book, err } = useBook()
  const [q, setQ] = useState('')
  const people = useMemo(() => (book?.people || []).filter(p => match(p, q.trim())), [book, q])
  const favs = people.filter(p => p.vip)
  const groups = useMemo(() => {
    const g: [string, Person[]][] = []
    for (const p of people) {
      const l = /^[a-zæøå]/i.test(fold(p.name)[0] || '') ? p.name[0].toUpperCase() : '#'
      const last = g[g.length - 1]
      if (last && last[0] === l) last[1].push(p); else g.push([l, [p]])
    }
    return g
  }, [people])
  return <div className="space-y-3">
    <label className="relative block">
      <SearchIcon className="text-ink-3 pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
      <Input value={q} onChange={e => setQ(e.target.value)} autoFocus={autoFocus} placeholder="Search name, number or e-mail" aria-label="Search contacts" className="pl-9" />
    </label>
    {err && <div className="text-dawn text-sm">{err}</div>}
    {!book && !err && <div className="text-ink-3 text-sm">Loading…</div>}
    {book && !book.from_contacts && <div className="text-ink-3 text-sm">{book.refreshing ? 'Reading your Contacts on the Mac mini – the first time takes a minute…' : 'Your Contacts on the Mac mini could not be read yet – showing people you mail with.'}</div>}
    {favs.length > 0 && !q && <section className="bg-card overflow-hidden rounded-lg border" aria-label="Favourites">
      <div className="ax-label border-b px-4 py-2">Favourites</div>
      <div className="divide-y">{favs.map(p => <Row key={'f' + p.name + (p.phones[0] || p.emails[0])} p={p} onOpen={onOpen} />)}</div>
    </section>}
    {book && !people.length && <div className="text-ink-3 text-sm">{q ? 'Nobody matches “' + q + '”.' : 'No contacts yet.'}</div>}
    {groups.length > 0 && <section className="bg-card overflow-hidden rounded-lg border" aria-label="All contacts">
      {groups.map(([l, list]) => <div key={l}>
        <div className="bg-bg-2/60 text-ink-3 sticky top-0 border-b px-4 py-1 font-mono text-[12px]">{l}</div>
        <div className="divide-y">{list.map(p => <Row key={p.name + (p.phones[0] || p.emails[0])} p={p} onOpen={onOpen} />)}</div>
      </div>)}
    </section>}
  </div>
}

function Act({ href, onClick, icon: I, label, sub, primary }: { href?: string; onClick?: () => void; icon: typeof Mail; label: string; sub?: string; primary?: boolean }) {
  const cls = cn('flex min-w-0 flex-1 flex-col items-center gap-1 rounded-lg border px-2 py-2.5 text-[13px] transition-colors',
    primary ? 'bg-fjord text-white border-fjord hover:opacity-90' : 'hover:bg-bg-2')
  const inner = <><I className="size-5" /><span className="font-medium">{label}</span>{sub && <span className={cn('max-w-full truncate text-[11px]', primary ? 'opacity-80' : 'text-ink-3')}>{sub}</span>}</>
  return href ? <a href={href} className={cls}>{inner}</a> : <button type="button" onClick={onClick} className={cls}>{inner}</button>
}

/** One contact, like the iPhone's card: name, favourite star, then every number and address with what it can do. */
export function ContactCard({ p, onClose }: { p: Person; onClose: () => void }) {
  const { ax, go } = useApp()
  const [vip, setVip] = useState(!!p.vip)
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState<false | string[]>(false)
  const [armed, setArmed] = useState(false)
  const owner = !!cache?.owner && ax.apiOk
  if (editing) return <ContactForm init={editing.length ? { ...p, emails: [...p.emails, ...editing], email_labels: [...(p.email_labels || p.emails.map(() => 'home')), ...editing.map(() => 'home')] } : p}
    onClose={() => setEditing(false)} onDone={onClose} />
  function del() {
    if (!armed) { setArmed(true); setTimeout(() => setArmed(false), 3000); return }
    onClose()
    withUndo(`Deleting ${p.name}…`, async () => {
      try { await ax.act('contact_delete', { id: p.id, title: p.name }, []); toast.success(`${p.name} deleted – Restore from the Activity log for 90 days`); load().catch(() => {}) }
      catch (e: any) { toast.error('Not deleted: ' + e.message) }
    })
  }
  async function star() {
    setBusy(true)
    try {
      if (vip) { await ax.act('vip_remove', { name: p.name, title: p.name }, []); setVip(false); toast(p.name + ' removed from Favourites (VIPs)') }
      else {
        await ax.act('vip_add', { name: p.name, title: p.name, address: p.emails[0] || p.phones[0] || '' }, [])
        setVip(true); toast(p.name + ' is a Favourite – a VIP in digests and for the call agent too')
      }
      loadVips(); load().catch(() => {})
    } catch (e: any) { toast.error(e.message) } finally { setBusy(false) }
  }
  const mail = (e: string) => p.private ? () => { location.href = links.mailto(e) } : () => { onClose(); openCompose({ to: e }) }
  return <Dialog open onOpenChange={o => { if (!o) onClose() }}>
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md" data-contact-card="">
      <div className="space-y-4 p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))]">
      <div className="flex flex-col items-center gap-2 pt-2 text-center">
        <Avatar p={p} size="lg" />
        <DialogTitle className="text-xl font-semibold">{p.name}</DialogTitle>
        {p.private && <div className="text-ink-3 text-[12.5px]">Private contact – Axella doesn't read or write for them; mail opens in Mail.</div>}
        <Button size="pill" variant={vip ? 'outline' : 'default'} disabled={busy || !ax.apiOk} onClick={star} aria-pressed={vip}>
          <Star className={cn(vip && 'text-dawn')} />{vip ? 'Favourite' : 'Add to Favourites'}</Button>
      </div>
      {(p.birthday || (owner && p.id)) && <BirthdayRow p={p} owner={owner} />}
      {p.phones.map(n => <div key={n} className="space-y-1.5">
        <div className="text-ink-3 text-[12.5px]">{pretty(n)}</div>
        <div className="flex gap-1.5">
          <Act href={links.sms(n)} icon={MessageCircle} label="Message" primary />
          <Act href={links.whatsapp(n)} icon={MessageCircle} label="WhatsApp" />
          <Act href={links.signal(n)} icon={MessageCircle} label="Signal" />
          <Act href={links.tel(n)} icon={Phone} label="Call" />
        </div>
      </div>)}
      {p.emails.map(e => <div key={e} className="space-y-1.5">
        <div className="text-ink-3 truncate text-[12.5px]">{e}</div>
        <div className="flex gap-1.5">
          <Act onClick={mail(e)} icon={Mail} label={p.private ? 'Mail' : 'New mail'} sub={p.private ? 'opens Mail' : 'Axella helps you write'} primary={!p.phones.length} />
          {!p.private && <Act href={links.mailto(e)} icon={Mail} label="Open in Mail" />}
        </div>
      </div>)}
      {(p.mail_only || []).map(e => <div key={e} className="space-y-1.5" data-mail-only="">
        <div className="text-ink-3 truncate text-[12.5px]">{e} · from your mail, not on the card in Contacts</div>
        <div className="flex gap-1.5">
          <Act onClick={mail(e)} icon={Mail} label={p.private ? 'Mail' : 'New mail'} sub={p.private ? 'opens Mail' : 'Axella helps you write'} primary={!p.phones.length && !p.emails.length} />
          {owner && p.id && <Act onClick={() => setEditing([e])} icon={Plus} label="Add to this contact" sub="opens Edit" />}
        </div>
      </div>)}
      {!IOS && p.phones.length > 0 && <p className="text-ink-3 text-[11.5px] leading-snug">Message, WhatsApp, Signal and Call open the app on this device – nothing is sent from the Mac mini. On a Mac, Message and Call go through your iPhone.</p>}
      {owner && <div className="flex flex-wrap gap-2 border-t pt-3">
        {(p.id || p.emails[0]) && <Button size="pill" variant="outline" data-open-person="" onClick={() => { onClose(); go({ kind: 'person', id: p.id || 'mail:' + p.emails[0].toLowerCase() }) }}><UserCircle />Open page</Button>}
        {p.id ? <>
          <Button size="pill" variant="outline" onClick={() => setEditing([])}><Pencil />Edit</Button>
          <Button size="pill" variant="ghost" className={cn('ml-auto', armed && 'text-danger')} onClick={del}><Trash2 />{armed ? 'Tap again to delete' : 'Delete'}</Button>
        </> : <Button size="pill" variant="outline" onClick={() => setEditing([])}><Plus />Add to Contacts</Button>}
      </div>}
      </div>
    </DialogContent>
  </Dialog>
}

/** Birthday on the card, and "Show birthday" – one line in the morning digest on the day (Favourites are on unless
    you switch it off). Never for a private contact. */
function BirthdayRow({ p, owner }: { p: Person; owner: boolean }) {
  const { ax } = useApp()
  const [on, setOn] = useState(!!p.birthday_shown)
  const [busy, setBusy] = useState(false)
  async function flip(v: boolean) {
    setBusy(true)
    try { await ax.act('birthday_show', { id: p.id, on: v, title: p.name }, []); setOn(v); load().catch(() => {}); toast(v ? `${p.name.split(' ')[0]}'s birthday will be in the morning digest on the day` : 'Not in the digest any more') }
    catch (e: any) { toast.error(e.message) } finally { setBusy(false) }
  }
  return <div className="space-y-1.5" data-birthday-row="">
    <div className="text-ink-3 text-[12.5px]">Birthday</div>
    <div className="text-sm">{p.birthday ? bdayLabel(p.birthday) : <span className="text-ink-3">None in Contacts – add it with Edit</span>}</div>
    {owner && p.id && !p.private && p.birthday && <label className="text-ink-2 flex min-h-8 items-center gap-2 text-[13px]">
      <Checkbox checked={on} disabled={busy || !ax.apiOk} onCheckedChange={v => flip(!!v)} data-birthday-show="" />
      Show in the morning digest on the day</label>}
    {p.private && p.birthday && <p className="text-ink-3 text-[11.5px]">A private contact – never in the digest.</p>}
    {owner && p.id && !p.private && p.birthday && p.vip && <p className="text-ink-3 -mt-1 pl-7 text-[11.5px]">On for Favourites unless you switch it off.</p>}
  </div>
}

/** The Contacts page (sidebar). */
export function ContactsView() {
  const [open, setOpen] = useState<Person | null>(null)
  return <div className="space-y-4" data-contacts-view="">
    <div className="flex items-start gap-3">
      <div className="min-w-0 flex-1">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><UserCircle className="size-5" />Contacts</h1>
        <p className="text-muted-foreground text-sm">Your Contacts from the Mac mini and people you mail with. Favourites are your VIPs.</p>
      </div>
      <Button size="pill" variant="outline" onClick={() => load(true).then(() => toast('Reading Contacts again on the Mac mini…')).catch(e => toast.error(e.message))}>Refresh</Button>
      <NewContactButton />
    </div>
    <KeepInTouchList />
    <ContactList onOpen={setOpen} autoFocus={!IOS} />
    {open && <ContactCard p={open} onClose={() => setOpen(null)} />}
  </div>
}

/* New › Message: pick someone, then choose how. */
export const openNewMessage = () => window.dispatchEvent(new CustomEvent('ax-new-message'))
export function NewMessageHost() {
  const [show, setShow] = useState(false)
  const [p, setP] = useState<Person | null>(null)
  const seen = useRef(false)
  useEffect(() => { const h = () => { seen.current = true; setP(null); setShow(true) }; addEventListener('ax-new-message', h); return () => removeEventListener('ax-new-message', h) }, [])
  if (p) return <ContactCard p={p} onClose={() => { setP(null); setShow(false) }} />
  if (!show) return null
  return <Dialog open onOpenChange={o => { if (!o) setShow(false) }}>
    <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-lg" data-new-message="">
      <div className="space-y-3 p-5">
      <DialogTitle className="text-lg font-semibold">New message</DialogTitle>
      <p className="text-ink-3 -mt-1 text-[13px]">Pick someone – then Mail, Message, WhatsApp or Signal.</p>
      <ContactList onOpen={setP} autoFocus={!IOS} />
      </div>
    </DialogContent>
  </Dialog>
}

function NewContactButton() {
  const { ax } = useApp()
  const { book } = useBook()
  const [open, setOpen] = useState(false)
  if (!book?.owner || !ax.apiOk) return null
  return <>
    <Button size="pill" onClick={() => setOpen(true)}><Plus />New contact</Button>
    {open && <ContactForm onClose={() => setOpen(false)} onDone={() => setOpen(false)} />}
  </>
}

const PHONE_LABELS = ['mobile', 'iphone', 'home', 'work', 'main', 'other']
const MAIL_LABELS = ['home', 'work', 'other']
type Line = { label: string; value: string }

/** Add or edit a contact in Contacts on the Mac mini: name, company, phones, e-mails (with labels). Owner only. */
export function ContactForm({ init, onClose, onDone }: { init?: Person; onClose: () => void; onDone: () => void }) {
  const { ax } = useApp()
  const edit = !!init?.id
  const guess = (init?.name || '').split(/\s+/)
  const [first, setFirst] = useState(init?.first ?? (edit ? '' : guess.slice(0, -1).join(' ') || guess[0] || ''))
  const [last, setLast] = useState(init?.last ?? (edit ? '' : guess.length > 1 ? guess[guess.length - 1] : ''))
  const [company, setCompany] = useState(init?.company || '')
  const [phones, setPhones] = useState<Line[]>(() => (init?.phones || []).map((v, i) => ({ label: init?.phone_labels?.[i] || 'mobile', value: v })))
  const [emails, setEmails] = useState<Line[]>(() => (init?.emails || []).map((v, i) => ({ label: init?.email_labels?.[i] || 'home', value: v })))
  const bm = /^(\d{4}|-)-(\d{2})-(\d{2})$/.exec(init?.birthday || '')
  const [bDay, setBDay] = useState(bm ? String(+bm[3]) : '')
  const [bMonth, setBMonth] = useState(bm ? String(+bm[2]) : '')
  const [bYear, setBYear] = useState(bm && bm[1] !== '-' ? bm[1] : '')
  const bOk = (!bDay && !bMonth && !bYear) || (!!bDay && !!bMonth && (!bYear || /^(18|19|20)\d\d$/.test(bYear)))
  const birthday = bDay && bMonth ? `${bYear || '-'}-${bMonth.padStart(2, '0')}-${bDay.padStart(2, '0')}` : ''
  const [busy, setBusy] = useState(false)
  async function save(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    const name = [first, last].filter(Boolean).join(' ') || company
    try {
      await ax.act(edit ? 'contact_update' : 'contact_add', { id: init?.id, first, last, company, title: name,
        phones: phones.filter(x => x.value.trim()), emails: emails.filter(x => x.value.trim()),
        // only when changed: a birthday Contacts has but Axella hasn't read yet is never cleared by accident
        ...(birthday !== (init?.birthday || '') ? { birthday } : {}) }, [])
      toast.success(edit ? name + ' saved in Contacts' : name + ' added to Contacts')
      load().catch(() => {}); onDone()
    } catch (x: any) { toast.error('Not saved: ' + x.message) } finally { setBusy(false) }
  }
  const lines = (list: Line[], set: (l: Line[]) => void, labels: string[], kind: 'tel' | 'email', placeholder: string) => <div className="space-y-1.5">
    {list.map((x, i) => <div key={i} className="flex gap-1.5">
      <NativeSelect aria-label="Label" value={x.label} onChange={e => set(list.map((y, j) => j === i ? { ...y, label: e.target.value } : y))} className="w-28 shrink-0">
        {labels.map(l => <option key={l} value={l}>{l}</option>)}</NativeSelect>
      <Input type={kind} value={x.value} placeholder={placeholder} onChange={e => set(list.map((y, j) => j === i ? { ...y, value: e.target.value } : y))} />
      <button type="button" aria-label="Remove" className="text-ink-3 hover:text-ink shrink-0 px-1" onClick={() => set(list.filter((_, j) => j !== i))}><X className="size-4" /></button>
    </div>)}
    {list.length < 6 && <button type="button" className="text-fjord inline-flex items-center gap-1 text-[13px] font-medium hover:underline"
      onClick={() => set([...list, { label: labels[0], value: '' }])}><Plus className="size-3.5" />Add {kind === 'tel' ? 'phone' : 'e-mail'}</button>}
  </div>
  return <Dialog open onOpenChange={o => { if (!o) onClose() }}>
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md" data-contact-form="">
      <form onSubmit={save} className="space-y-3 p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] text-sm">
        <DialogTitle className="text-lg font-semibold">{edit ? 'Edit contact' : 'New contact'}</DialogTitle>
        <div className="grid grid-cols-2 gap-2">
          <label className="block"><span className="mb-1 block font-medium">First name</span><Input value={first} maxLength={60} onChange={e => setFirst(e.target.value)} autoFocus /></label>
          <label className="block"><span className="mb-1 block font-medium">Last name</span><Input value={last} maxLength={60} onChange={e => setLast(e.target.value)} /></label>
        </div>
        <label className="block"><span className="mb-1 block font-medium">Company</span><Input value={company} maxLength={80} onChange={e => setCompany(e.target.value)} /></label>
        <div><span className="mb-1 block font-medium">Phone</span>{lines(phones, setPhones, PHONE_LABELS, 'tel', '+45 00 00 00 00')}</div>
        <div><span className="mb-1 block font-medium">E-mail</span>{lines(emails, setEmails, MAIL_LABELS, 'email', 'name@example.com')}</div>
        <div><span className="mb-1 block font-medium">Birthday</span>
          <div className="flex gap-1.5">
            <NativeSelect aria-label="Day" value={bDay} onChange={e => setBDay(e.target.value)} className="w-20 shrink-0">
              <option value="">Day</option>{Array.from({ length: 31 }, (_, i) => <option key={i} value={String(i + 1)}>{i + 1}</option>)}</NativeSelect>
            <NativeSelect aria-label="Month" value={bMonth} onChange={e => setBMonth(e.target.value)} className="min-w-0 flex-1">
              <option value="">Month</option>{MONTHS.map((m, i) => <option key={m} value={String(i + 1)}>{m}</option>)}</NativeSelect>
            <Input aria-label="Year (optional)" inputMode="numeric" placeholder="Year" value={bYear} maxLength={4} onChange={e => setBYear(e.target.value.replace(/\D/g, ''))} className="w-20 shrink-0" />
            {(bDay || bMonth || bYear) && <button type="button" aria-label="No birthday" className="text-ink-3 hover:text-ink shrink-0 px-1" onClick={() => { setBDay(''); setBMonth(''); setBYear('') }}><X className="size-4" /></button>}
          </div>
          {!bOk && <p className="text-dawn mt-1 text-[12px]">Pick a day and a month; the year is optional.</p>}
        </div>
        <p className="text-ink-3 text-[12px]">Saved in Contacts on the Mac mini – it syncs to your phone. Photo, address and notes: change them in Contacts.</p>
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy || !bOk || !(first.trim() || last.trim() || company.trim())}>{edit ? 'Save' : 'Add contact'}</Button>
        </div>
      </form>
    </DialogContent>
  </Dialog>
}
