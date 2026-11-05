/* Receipts → Renewals (setup/renewals.py): things that expire or renew on a date and need action in time – insurance,
   domains, memberships, a passport, the car's inspection. From renewal and expiry mails (genuine senders only, each a
   suggestion you confirm), yearly subscriptions (linked, not copied) and entries you add by hand. Rules only on the
   Mac mini. Never a document or policy number. Axella never renews or pays anything. */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { CalendarClock, Check, Plus, RotateCw, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input, NativeSelect } from '@/components/ui/input'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { cn } from '@/lib/utils'

export interface Renewal { id: string; name: string; kind: string; label?: string; date: string; days?: number; lead_days?: number; lead_from?: string
  cost?: number | null; currency?: string | null; ctx?: 'work' | 'private' | null; auto_renews?: boolean; source?: string; notes?: string | null
  state?: 'lead' | 'waiting' | 'after' | 'handled' | 'snoozed' | 'past' | 'linked'; recurring?: boolean; linked?: boolean; task_id?: string | null }
interface Suggestion { message_id: string; account?: string; kind: string; name: string; date: string; cost?: number | null; currency?: string | null; auto_renews?: boolean; domain?: string }
interface Warning { trip: string; trip_title: string; renewal: string; months: number; text: string }
interface View { rows: Renewal[]; past: Renewal[]; suggestions: Suggestion[]; trip_warnings: Warning[]; cards: Renewal[]
  kinds: Record<string, { label: string; lead_days: number; recurring: boolean }> }

let cache: Promise<View | null> | null = null
export const loadRenewals = (fresh = false) => {
  if (fresh || !cache) cache = get<View>('renewals').then(r => ((r as any).rows ? r : null)).catch(() => null)
  return cache
}
export function useRenewals() {
  const [v, setV] = useState<View | null>(null)
  useEffect(() => { loadRenewals().then(setV) }, [])
  return { v, reload: () => loadRenewals(true).then(setV) }
}

const day = (s?: string | null) => s ? new Date(s.slice(0, 10) + 'T12:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: new Date(s).getFullYear() === new Date().getFullYear() ? undefined : 'numeric' }) : ''
const money = (n?: number | null, c?: string | null) => n != null ? n.toLocaleString('da-DK', { maximumFractionDigits: 2 }) + (c ? ' ' + c : '') : ''
const left = (d?: number) => d == null ? '' : d < 0 ? `${-d} day${d === -1 ? '' : 's'} ago` : d === 0 ? 'today' : d < 45 ? `in ${d} day${d === 1 ? '' : 's'}` : `in ${Math.round(d / 30.4)} months`

function useAct(reload: () => void) {
  const { ax } = useApp()
  const [busy, setBusy] = useState<string | null>(null)
  const act = async (key: string, action: string, body: Record<string, unknown>, msg?: string) => {
    setBusy(key)
    try { await ax.act(action, body, ['tasks']); if (msg) toast(msg); await reload(); return true }
    catch (e: any) { toast.error(e.message); return false } finally { setBusy(null) }
  }
  return { busy, act }
}

export function RenewalsView() {
  const { v, reload } = useRenewals()
  const { busy, act } = useAct(reload)
  const [adding, setAdding] = useState<Partial<Renewal> & { message_id?: string } | null>(null)
  const [showPast, setShowPast] = useState(false)
  if (!v) return <div className="text-ink-3 text-sm">Loading…</div>
  const now = new Date(), m0 = now.getMonth(), y0 = now.getFullYear()
  const bucket = (r: Renewal) => { const d = new Date(r.date + 'T12:00'); const m = (d.getFullYear() - y0) * 12 + d.getMonth() - m0; return m <= 0 ? 'This month' : m === 1 ? 'Next month' : 'Later' }
  const groups = ['This month', 'Next month', 'Later'].map(g => [g, v.rows.filter(r => bucket(r) === g)] as const).filter(([, l]) => l.length)
  return <div className="space-y-4" data-renewals="">
    {v.trip_warnings.map(w => <div key={w.trip + w.renewal} className="bg-dawn/10 rounded-lg border px-4 py-2.5 text-sm" data-passport-warning="">{w.text}</div>)}
    {v.suggestions.length > 0 && <Card className="overflow-hidden" data-renewal-suggestions="">
      <div className="ax-label border-b px-4 py-2.5">From your mail – add the ones that are renewals</div>
      <div className="divide-y">{v.suggestions.map(s => <div key={s.message_id} className="flex flex-wrap items-center gap-2 px-4 py-2.5 text-sm">
        <span className="min-w-0 flex-1 basis-[14rem]"><span className="font-medium">{s.name}</span> <span className="text-ink-3">· {v.kinds[s.kind]?.label} · {day(s.date)}{s.cost ? ' · ' + money(s.cost, s.currency) : ''}{s.domain ? ' · from ' + s.domain : ''}</span></span>
        <Button size="pill" variant="outline" disabled={!!busy} onClick={() => setAdding({ ...s, message_id: s.message_id })}><Plus />Add…</Button>
        <Button size="pill" variant="ghost" disabled={!!busy} onClick={() => act(s.message_id, 'renewal_not', { message_id: s.message_id, title: 'Renewal' }, 'Not offered again')}><X />Not a renewal</Button>
      </div>)}</div>
    </Card>}
    <div className="flex flex-wrap items-center gap-2">
      <Button size="pill" onClick={() => setAdding({ kind: 'insurance' })}><Plus />Add a renewal</Button>
      <Button size="pill" variant="outline" disabled={!!busy} onClick={() => act('scan', 'renewal_scan', { title: 'Renewals' }, 'Checking your mail for renewals – a minute or two')}><RotateCw />Check mail</Button>
      <span className="text-ink-3 text-[12.5px]">Notices from e-Boks or Digital Post: add them by hand.</span>
    </div>
    {adding && <RenewalForm init={adding} kinds={v.kinds} busy={!!busy} onCancel={() => setAdding(null)}
      onSave={async body => { if (await act('add', body.id ? 'renewal_update' : 'renewal_add', { ...body, title: body.name }, body.id ? 'Saved' : 'Added to Renewals')) setAdding(null) }} />}
    {!v.rows.length ? <Card className="text-ink-3 p-4 text-sm">Nothing in the next 12 months yet.</Card>
      : groups.map(([g, list]) => <Card key={g} className="overflow-hidden">
        <div className="ax-label border-b px-4 py-2.5">{g}</div>
        <div className="divide-y">{list.map(r => <RenewalRow key={r.id} r={r} busy={!!busy} act={act} onEdit={() => setAdding(r)} />)}</div>
      </Card>)}
    {v.past.length > 0 && <div><button className="text-fjord text-[13px] font-medium" onClick={() => setShowPast(!showPast)}>{showPast ? 'Hide past' : `Past (${v.past.length})`}</button>
      {showPast && <Card className="mt-2 divide-y">{v.past.map(r => <div key={r.id} className="text-ink-3 flex items-center gap-2 px-4 py-2 text-sm"><span className="min-w-0 flex-1 truncate">{r.name}</span>{day(r.date)}</div>)}</Card>}</div>}
    <p className="text-ink-3 text-xs">Found on the Mac mini from renewal and expiry mails (genuine senders only) and what you add. Yearly subscriptions are shown from Subscriptions, not counted twice. Axella never stores document or policy numbers, and never renews or pays anything.</p>
  </div>
}

function RenewalRow({ r, busy, act, onEdit }: { r: Renewal; busy: boolean; act: (k: string, a: string, b: Record<string, unknown>, m?: string) => Promise<boolean>; onEdit: () => void }) {
  const next = r.recurring ? (() => { const d = new Date(r.date + 'T12:00'); d.setMonth(d.getMonth() + (r.kind === 'vehicle_inspection' ? 24 : 12)); return d.toISOString().slice(0, 10) })() : ''
  const [nd, setNd] = useState(next)
  return <div className="space-y-1.5 px-4 py-2.5 text-sm" data-renewal={r.id} data-state={r.state}>
    <div className="flex flex-wrap items-baseline gap-x-2">
      <button className="min-w-0 flex-1 truncate text-left font-medium" onClick={r.linked ? undefined : onEdit} disabled={r.linked}>{r.name}</button>
      <span className="text-ink-2 font-mono text-[13px]">{day(r.date)}</span>
      <span className={cn('text-[12.5px]', r.state === 'lead' || r.state === 'after' ? 'text-dawn' : 'text-ink-3')}>{left(r.days)}</span>
    </div>
    <div className="text-ink-3 text-[12.5px]">{[r.label, r.cost ? money(r.cost, r.currency) : '', r.auto_renews ? 'renews by itself' : '', r.linked ? 'from Subscriptions' : '',
      r.state === 'lead' ? 'time to act' : r.state === 'snoozed' ? 'snoozed' : r.state === 'handled' ? (r.task_id ? 'in To do' : 'letting it renew') : '',
      r.notes || ''].filter(Boolean).join(' · ')}</div>
    {r.state === 'after' && (r.recurring
      ? <div className="flex flex-wrap items-center gap-2"><span>Renewed? Next date</span><Input type="date" className="h-8 w-40 text-xs" value={nd} onChange={e => setNd(e.target.value)} />
          <Button size="pill" variant="outline" disabled={busy || !nd} onClick={() => act(r.id, 'renewal_renewed', { id: r.id, next: nd, title: r.name }, 'Next date saved')}><Check />Save</Button>
          <Button size="pill" variant="ghost" disabled={busy} onClick={() => act(r.id, 'renewal_past', { id: r.id, title: r.name }, 'Moved to Past')}>It ended</Button></div>
      : <div className="flex flex-wrap items-center gap-2"><Button size="pill" variant="outline" disabled={busy} onClick={onEdit}>New date…</Button>
          <Button size="pill" variant="ghost" disabled={busy} onClick={() => act(r.id, 'renewal_past', { id: r.id, title: r.name }, 'Moved to Past')}>Move to Past</Button></div>)}
  </div>
}

function RenewalForm({ init, kinds, busy, onSave, onCancel }: { init: Partial<Renewal> & { message_id?: string }; kinds: View['kinds']; busy: boolean
  onSave: (b: Record<string, any>) => void; onCancel: () => void }) {
  const [f, setF] = useState({ name: init.name || '', kind: init.kind || 'insurance', date: init.date || '', lead_days: init.lead_days ? String(init.lead_days) : '',
    cost: init.cost != null ? String(init.cost) : '', currency: init.currency || 'DKK', auto_renews: !!init.auto_renews, ctx: init.ctx || '', notes: init.notes || '' })
  const set = (k: keyof typeof f) => (e: any) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  return <Card className="space-y-2 p-4 text-sm" data-renewal-form="">
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      <label className="block"><span className="mb-1 block font-medium">Name</span><Input value={f.name} maxLength={80} onChange={set('name')} placeholder="Car insurance" autoFocus /></label>
      <label className="block"><span className="mb-1 block font-medium">Kind</span>
        <NativeSelect value={f.kind} onChange={set('kind')}>{Object.entries(kinds).map(([k, x]) => <option key={k} value={k}>{x.label}</option>)}</NativeSelect></label>
      <label className="block"><span className="mb-1 block font-medium">{kinds[f.kind]?.recurring ? 'Renews on' : 'Expires on'}</span><Input type="date" value={f.date} onChange={set('date')} /></label>
      <label className="block"><span className="mb-1 block font-medium">Remind me (days before)</span><Input type="number" min={1} max={400} value={f.lead_days} placeholder={String(kinds[f.kind]?.lead_days || 30)} onChange={set('lead_days')} /></label>
      <label className="block"><span className="mb-1 block font-medium">Cost last time (optional)</span>
        <span className="flex gap-1.5"><Input type="number" min={0} step="0.01" value={f.cost} onChange={set('cost')} />
          <NativeSelect className="w-24" value={f.currency} onChange={set('currency')}>{['DKK', 'EUR', 'USD', 'SEK', 'NOK', 'GBP', 'CHF'].map(c => <option key={c}>{c}</option>)}</NativeSelect></span></label>
      <label className="block"><span className="mb-1 block font-medium">World</span>
        <NativeSelect value={f.ctx} onChange={set('ctx')}><option value="">Both</option><option value="private">Private</option><option value="work">Work</option></NativeSelect></label>
    </div>
    <label className="flex items-center gap-2"><input type="checkbox" checked={f.auto_renews} onChange={set('auto_renews')} />Renews by itself</label>
    <label className="block"><span className="mb-1 block font-medium">Note (optional)</span><Input value={f.notes} maxLength={500} onChange={set('notes')} placeholder="Compare with two other offers" /></label>
    <p className="text-ink-3 text-[12px]">Never write a passport, ID, licence or policy number here – Axella refuses them.</p>
    <div className="flex justify-end gap-2">
      <Button variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button>
      <Button disabled={busy || !f.name.trim() || !f.date} onClick={() => onSave({ ...(init.id ? { id: init.id } : {}), ...(init.message_id ? { message_id: init.message_id, source: 'mail' } : {}),
        name: f.name, kind: f.kind, date: f.date, lead_days: f.lead_days || null, cost: f.cost === '' ? null : Number(f.cost), currency: f.currency,
        auto_renews: f.auto_renews, ctx: f.ctx || null, notes: f.notes })}>{init.id ? 'Save' : 'Add'}</Button>
    </div>
  </Card>
}

/** Today / To do: the renewals that reached their lead time – a suggested To do card, never made by itself. */
export function RenewalsCard() {
  const { v, reload } = useRenewals()
  const { busy, act } = useAct(reload)
  if (!v || !v.cards.length) return null
  return <section className="bg-card space-y-3 rounded-lg border p-4" data-renewals-card="">
    <div className="flex items-center gap-2"><CalendarClock className="text-ink-3 size-4" /><span className="ax-label">Renewals</span></div>
    {v.cards.map(r => <div key={r.id} className="space-y-1.5 text-sm" data-renewal-card="">
      <div><b className="font-medium">{r.name}</b> {r.auto_renews ? 'renews' : r.kind === 'passport' || r.kind === 'id_card' || r.kind === 'driving_licence' ? 'expires' : 'is due'} {day(r.date)}{r.cost ? ` – ${money(r.cost, r.currency)} last time` : ''}.</div>
      <div className="flex flex-wrap gap-2">
        <Button size="pill" disabled={!!busy} onClick={() => act(r.id, 'renewal_todo', { id: r.id, title: r.name }, 'Added to To do')}><Plus />Add to To do</Button>
        <Button size="pill" variant="outline" disabled={!!busy} onClick={() => act(r.id, 'renewal_snooze', { id: r.id, for: 'week', title: r.name }, 'Snoozed a week')}>Snooze a week</Button>
        <Button size="pill" variant="ghost" disabled={!!busy} onClick={() => act(r.id, 'renewal_snooze', { id: r.id, for: 'month', title: r.name }, 'Snoozed a month')}>A month</Button>
        {r.auto_renews && <Button size="pill" variant="ghost" disabled={!!busy} onClick={() => act(r.id, 'renewal_let_renew', { id: r.id, title: r.name }, 'Letting it renew')}>Let it renew</Button>}
      </div>
    </div>)}
  </section>
}

/** On a trip: the passport check (shown on Renewals too). */
export function TripPassportWarning({ tripId }: { tripId: string }) {
  const { v } = useRenewals()
  const w = (v?.trip_warnings || []).filter(x => x.trip === tripId)
  if (!w.length) return null
  return <span className="text-dawn block text-[12.5px]" data-trip-passport="">{w.map(x => x.text).join(' ')}</span>
}
