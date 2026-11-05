import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Lock, Pencil, Plus, Trash2 } from '@/components/ax-icons'
import { SectionCard } from '@/components/Section'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input, NativeSelect } from '@/components/ui/input'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { cn } from '@/lib/utils'

/* Private contacts (setup/privacy.py). Per contact and per platform:
   normal – Axella reads and summarises as usual; private – Axella only knows that something arrived (who, where, how
   many), the text never reaches Claude; hidden – ignored. Enforced on the Mac mini before any Claude run sees the data,
   never by asking Claude to skip something. Where it isn't enforced yet, the page says so. */
type Level = 'normal' | 'private' | 'hidden'
interface PContact { id: string; name: string; ids: string[]; levels: Record<string, Level> }
interface SignalStatus { installed: boolean; linked: boolean; ok?: boolean; account?: string | null; error?: string | null; received_at?: string | null; chats: number }
interface PSettings { broken?: boolean; defaults: Record<string, Level>; discreet: boolean; discreet_push?: boolean; notify?: boolean; contacts: PContact[]; channels: string[]; enforced: string[]; signal?: SignalStatus }
export interface PrivateChat { channel: string; contact?: string | null; name: string; group?: boolean; unread: number; waiting: number; last_at?: string; last_from_me?: boolean; open: string }

const CH: Record<string, string> = { mail: 'Mail', imessage: 'iMessage', whatsapp: 'WhatsApp', signal: 'Signal', calls: 'Calls' }
const LV: Record<Level, string> = { normal: 'Normal', private: 'Private', hidden: 'Hidden' }
const SOON: Record<string, string> = {}

export function PrivacyCard() {
  const { ax } = useApp()
  const [s, setS] = useState<PSettings | null>(null)
  const [edit, setEdit] = useState<Partial<PContact> | null>(null)
  // an older Mac mini or a demo backend may leave fields out: fill them so the card never breaks
  const load = useCallback(() => get<PSettings>('privacy').then(j => setS({ ...j, defaults: j.defaults && typeof j.defaults === 'object' ? j.defaults : {},
    contacts: Array.isArray(j.contacts) ? j.contacts : [], channels: Array.isArray(j.channels) ? j.channels : [], enforced: Array.isArray(j.enforced) ? j.enforced : [],
    discreet: !!j.discreet })).catch(() => {}), [])
  useEffect(() => { if (ax.apiOk) load() }, [ax.apiOk, load])
  const send = async (p: object, ok: string) => {
    try { const r: any = await ax.act('privacy_set', p, []); setS(r?.result || r); toast(ok); return true } catch (e: any) { toast.error('Not saved: ' + e.message); return false }
  }
  if (!s) return null
  const later = s.channels.filter(c => !s.enforced.includes(c))
  return (
    <SectionCard id="privacy" icon={Lock} title="Private contacts" sub={`${s.contacts.length} contact${s.contacts.length === 1 ? '' : 's'} · Private and Hidden never reach Claude – Normal does`}>
      <div className="space-y-4 p-4 text-sm">
        {s.broken && <div className="border-danger text-danger rounded-md border px-3 py-2 text-[13px]" role="alert" data-privacy-broken="">
          <b className="font-semibold">Your privacy settings can't be read.</b> state/privacy.json on the Mac mini is damaged or not readable, so everyone is treated as private and WhatsApp, Signal and the Private card pause. Fix or restore the file – changes here are refused until then.</div>}
        <p className="text-muted-foreground text-xs">For conversations that aren't for an assistant. <b className="text-ink-2 font-medium">Private</b>: Axella only shows that a message arrived – who, where and how many – on a Private card on Today; the text is never read and never sent to Claude. <b className="text-ink-2 font-medium">Hidden</b>: ignored completely. Checked on the Mac mini before any Axella run starts, and Axella's runs can't see this list either. <b className="text-ink-2 font-medium">From now on:</b> what Axella already summarised before you made someone private stays in older digests, search and Insights – only saved calls are moved out at once.</p>

        <div>
          <div className="ax-label mb-2">Default per platform</div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {s.channels.map(c => <label key={c} className="grid gap-1 text-[13px]">
              <span className="text-ink-2">{CH[c] || c}{!s.enforced.includes(c) && <span className="text-ink-3"> · from {SOON[c] || 'later'}</span>}</span>
              <NativeSelect value={s.defaults[c]} onChange={e => send({ defaults: { [c]: e.target.value } }, `${CH[c]}: ${LV[e.target.value as Level]} by default – the people on your list keep their setting`)}>
                {(['normal', 'private', 'hidden'] as Level[]).map(l => <option key={l} value={l}>{LV[l]}</option>)}</NativeSelect>
            </label>)}
          </div>
        </div>

        <div>
          <div className="ax-label mb-2">Contacts</div>
          {!s.contacts.length && <p className="text-ink-3 text-[13px]">No private contacts yet.</p>}
          <ul className="divide-y rounded-lg border">{s.contacts.map(c => <li key={c.id} className="flex items-start gap-3 px-3 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="font-medium">{c.name}</div>
              <div className="text-ink-3 truncate font-mono text-[12px]">{c.ids.join(' · ')}</div>
              {/* what actually applies, per platform – "Normal" means Claude reads it there */}
              <div className="text-ink-2 mt-0.5 text-[13px]">{(['private', 'hidden', 'normal'] as Level[]).map(l => {
                const chs = s.channels.filter(ch => (c.levels[ch] || c.levels.all || s.defaults[ch]) === l)
                return chs.length ? `${LV[l]} on ${chs.map(ch => CH[ch] || ch).join(', ')}` : null
              }).filter(Boolean).join(' · ')}</div>
            </div>
            <button aria-label={'Edit ' + c.name} className="text-ink-3 hover:text-ink p-1" onClick={() => setEdit(c)}><Pencil className="size-4" /></button>
            <button aria-label={'Remove ' + c.name} className="text-ink-3 hover:text-destructive p-1" onClick={() => send({ remove: c.id }, c.name + ' removed – the defaults apply again')}><Trash2 className="size-4" /></button>
          </li>)}</ul>
          <Button size="sm" variant="outline" className="mt-2" onClick={() => setEdit({ name: '', ids: [], levels: {} })}><Plus />Add a private contact</Button>
        </div>

        {edit && <ContactEditor c={edit} channels={s.channels} defaults={s.defaults} onCancel={() => setEdit(null)} onSave={async c => { if (await send({ contact: c }, c.name + ' saved')) setEdit(null) }} />}

        {s.signal && <div className="rounded-lg border px-3 py-2.5 text-[13px]">
          <div className="flex items-center gap-2"><span className="font-medium">Signal</span>
            <span className={cn('ml-auto', s.signal.ok ? 'text-fjord' : 'text-ink-3')}>{!s.signal.installed ? 'not installed' : !s.signal.linked ? 'not linked yet' : s.signal.ok ? 'connected' : 'problem'}</span></div>
          <div className="text-ink-3 mt-0.5">{!s.signal.installed ? 'Install signal-cli on the Mac mini and link it from Signal on your phone – see SETUP "Signal".'
            : !s.signal.linked ? 'Link the Mac mini from Signal on your phone: Settings → Linked devices – see SETUP "Signal".'
            : s.signal.error ? s.signal.error
            : `Linked to your number ${s.signal.account || ''} as a device that only receives – remove it any time under Linked devices on your phone. Last checked ${s.signal.received_at ? new Date(s.signal.received_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '–'}; ${s.signal.chats} normal chat${s.signal.chats === 1 ? '' : 's'} in the last 48 h.`}</div>
        </div>}

        <label className="flex items-start gap-2.5"><input type="checkbox" className="accent-fjord mt-0.5 size-4" checked={s.notify !== false} onChange={e => send({ notify: e.target.checked }, e.target.checked ? 'You get a notification for private messages' : 'No notifications for private messages')} />
          <span><span className="font-medium">Notify me</span><span className="text-ink-3 block text-[13px]">A notification on your devices when a private contact writes – who and where, never the text (Axella doesn't have it).</span></span></label>

        {s.notify !== false && <label className="ml-6 flex items-start gap-2.5"><input type="checkbox" className="accent-fjord mt-0.5 size-4" checked={!!s.discreet_push} onChange={e => send({ discreet_push: e.target.checked }, e.target.checked ? 'Notifications without names' : 'Notifications show who wrote')} />
          <span><span className="font-medium">Leave names out of notifications</span><span className="text-ink-3 block text-[13px]">"1 new private message on Signal" on the lock screen instead of the name.</span></span></label>}

        <label className="flex items-start gap-2.5"><input type="checkbox" className="accent-fjord mt-0.5 size-4" checked={s.discreet} onChange={e => send({ discreet: e.target.checked }, e.target.checked ? 'Names hidden on the dashboard' : 'Names shown on the dashboard')} />
          <span><span className="font-medium">Discreet dashboard</span><span className="text-ink-3 block text-[13px]">The Private card says "2 private messages on Signal" instead of who they're from, and search leaves the name out – for when someone looks at your screen. Notifications have their own switch above.</span></span></label>

        {later.length > 0 && <p className="text-ink-3 text-[12px]">Works today for {s.enforced.map(c => CH[c]).join(', ')}. {later.map(c => CH[c]).join(', ')}: the setting is saved now and takes effect when that part is built – until then those messages are read as before.</p>}
      </div>
    </SectionCard>
  )
}

function ContactEditor({ c, channels, defaults, onCancel, onSave }: { c: Partial<PContact>; channels: string[]; defaults: Record<string, Level>; onCancel: () => void; onSave: (c: PContact) => void }) {
  const [name, setName] = useState(c.name || '')
  const [ids, setIds] = useState((c.ids || []).join('\n'))
  const [lv, setLv] = useState<Record<string, Level>>({ ...(c.levels || {}) })
  return <form className="bg-bg-2/50 space-y-3 rounded-lg border p-3" onSubmit={e => {
    e.preventDefault()
    const own = Object.fromEntries(Object.entries(lv).filter(([, v]) => v)) as Record<string, Level>   // only what differs from "default"
    onSave({ id: c.id || '', name: name.trim(), ids: ids.split(/[\n,]+/).map(x => x.trim()).filter(Boolean), levels: own })
  }}>
    <label className="grid gap-1 text-[13px] font-medium">Name<Input autoFocus value={name} onChange={e => setName(e.target.value)} placeholder="How you call them" required /></label>
    <label className="grid gap-1 text-[13px] font-medium">Phone numbers and e-mail addresses <span className="text-ink-3 font-normal">one per line – with country code, e.g. +45 00 00 00 00</span>
      <textarea value={ids} onChange={e => setIds(e.target.value)} rows={2} required
        className="border-input bg-card focus-visible:ring-ring/50 rounded-md border px-3 py-2 font-mono text-[14px] font-normal outline-none focus-visible:ring-2" /></label>
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{channels.map(ch => <label key={ch} className="grid gap-1 text-[13px]">
      <span className="text-ink-2">{CH[ch] || ch}</span>
      <NativeSelect value={lv[ch] || ''} onChange={e => setLv({ ...lv, [ch]: e.target.value as Level })}>
        <option value="">Default ({LV[defaults[ch]]})</option>
        {(['normal', 'private', 'hidden'] as Level[]).map(l => <option key={l} value={l}>{LV[l]}</option>)}</NativeSelect></label>)}</div>
    <div className="flex justify-end gap-2"><Button type="button" size="sm" variant="ghost" onClick={onCancel}>Cancel</Button><Button type="submit" size="sm">Save</Button></div>
  </form>
}

/* Today: who wrote privately – never what. Opens the app itself. */
export function PrivateCard() {
  const { ax } = useApp()
  const [d, setD] = useState<{ chats: PrivateChat[]; discreet: boolean } | null>(null)
  useEffect(() => {
    if (!ax.apiOk) return
    const f = () => get<{ chats: PrivateChat[]; discreet: boolean }>('private_inbox').then(setD).catch(() => {})
    f(); const t = setInterval(() => !document.hidden && f(), 60000); addEventListener('focus', f)
    return () => { clearInterval(t); removeEventListener('focus', f) }
  }, [ax.apiOk])
  const open = (d?.chats || []).filter(c => !c.last_from_me && (c.unread > 0 || c.waiting > 0))
  if (!open.length) return null
  return <Card className="overflow-hidden">
    <div className="flex items-center gap-2 border-b px-4 py-2.5"><Lock className="text-ink-3 size-3.5" /><span className="ax-label">Private</span>
      <span className="text-ink-3 ml-auto text-[12px]">not read by Axella</span></div>
    <div className="divide-y">{open.map((c, i) => <a key={i} href={c.open} className="hover:bg-bg-2 flex items-baseline gap-2 px-4 py-2.5 text-sm">
      <span className={cn('min-w-0 flex-1 truncate', !d!.discreet && 'font-medium')}>
        {d!.discreet ? `${c.unread || c.waiting} private ${c.channel === 'calls' ? 'call' : 'message'}${(c.unread || c.waiting) === 1 ? '' : 's'}` : c.name}</span>
      <span className="text-ink-3 shrink-0 text-[13px]">{d!.discreet ? '' : c.channel === 'calls' ? `${c.unread || c.waiting} ${(c.unread || c.waiting) === 1 ? 'call' : 'calls'} · ` : `${c.unread || c.waiting} new · `}{CH[c.channel] || c.channel}</span>
      <span className="text-ink-3 shrink-0 font-mono text-[12px]">{c.last_at ? new Date(c.last_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : ''}</span>
    </a>)}</div>
  </Card>
}
