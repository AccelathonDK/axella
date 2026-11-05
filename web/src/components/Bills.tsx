/* Bills (feature pack §3, setup/bills.py): a bill is a To do with type "bill" – one list, a Bills filter, and these
   pieces: suggested bill cards (from the Receipts register; you confirm them), "Looks paid" and the payment details
   on a bill's row. Amounts are exact, in their own currency, in mono. Axella never pays and never opens bank links. */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Check, CheckCheck, Copy, FileText, Mail, Pencil, Receipt, X } from '@/components/ax-icons'
import { openMailInAxella } from '@/components/MailReader'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import type { Bill, BillRef, Task } from '@/lib/types'
import { cn } from '@/lib/utils'

export interface BillCard { id: string; payee: string; amount: number | null; currency?: string | null; due?: string | null; kind?: string
  date?: string; reference: BillRef; account?: string; message_id: string; deep_link?: string | null; subject?: string; attachments: string[]
  /** safety: a first bill from this sender, or details that differ from the payee's earlier bills – details hidden until shown */
  first_time?: boolean; details_differ?: boolean; sender_differs?: boolean; reference_hidden?: boolean }
interface BillsData { suggestions: BillCard[]; looks_paid: { id: string; task_id: string; receipt: string }[]; refs?: Record<string, BillRef> }

export const money = (a?: number | null, cur?: string | null) => a == null ? '' :
  a.toLocaleString('da-DK', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + (cur ? ' ' + cur : '')
const day = (s?: string | null) => s ? new Date(s.slice(0, 10) + 'T12:00').toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }) : ''
const REF_LABEL: Record<keyof BillRef, string> = { fi: 'FI', iban: 'IBAN', account: 'Reg./account', mobilepay: 'MobilePay', invoice_no: 'Invoice no.' }
const pdfUrl = (account: string | undefined, mid: string, i: number) => `api/attachment?account=${encodeURIComponent(account || 'iCloud')}&id=${encodeURIComponent(mid)}&n=${i + 1}`

let cache: BillsData | null = null
const subs = new Set<(d: BillsData) => void>()
export const reloadBills = () => get<BillsData>('bills').then(d => { cache = d; subs.forEach(f => f(d)); return d })
function useBills() {
  const [d, setD] = useState<BillsData | null>(cache)
  useEffect(() => { subs.add(setD); reloadBills().catch(() => {}); return () => { subs.delete(setD) } }, [])
  return d
}

/** The payment reference: each one with Copy – never a link. */
export function RefList({ r }: { r: BillRef }) {
  const keys = (Object.keys(REF_LABEL) as (keyof BillRef)[]).filter(k => r[k])
  if (!keys.length) return null
  return <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[13px]" data-bill-ref="">
    {keys.map(k => <div key={k} className="contents">
      <dt className="text-ink-3">{REF_LABEL[k]}</dt>
      <dd className="flex min-w-0 items-center gap-1.5"><span className="truncate font-mono">{r[k]}</span>
        <button type="button" aria-label={'Copy ' + REF_LABEL[k]} className="text-ink-3 hover:text-ink shrink-0"
          onClick={() => navigator.clipboard.writeText(String(r[k]).replace(/\s/g, k === 'fi' ? ' ' : '')).then(() => toast(REF_LABEL[k] + ' copied'), () => {})}><Copy className="size-3.5" /></button></dd>
    </div>)}
  </dl>
}

function Source({ account, mid, subject, attachments }: { account?: string; mid: string; subject?: string; attachments: string[] }) {
  return <div className="flex flex-wrap gap-x-3 gap-y-1 text-[12.5px]">
    {mid && account && <button type="button" className="text-fjord inline-flex items-center gap-1 hover:underline" onClick={() => openMailInAxella({ account, message_id: mid, subject })} data-bill-open-mail=""><Mail className="size-3" />Open mail</button>}
    {attachments.map((a, i) => /\.pdf$/i.test(a) && <a key={i} className="text-fjord inline-flex items-center gap-1 hover:underline" href={pdfUrl(account, mid, i)} target="_blank" rel="noopener noreferrer">
      <FileText className="size-3" />{a.length > 28 ? a.slice(0, 25) + '…' : a}</a>)}
  </div>
}

/** Suggested bills, and "Looks paid" for bills in To do – at the top of To do. Nothing here without a card to show. */
export function BillsCard() {
  const { ax } = useApp()
  const d = useBills()
  const [edit, setEdit] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [shown, setShown] = useState<Set<string>>(new Set())
  if (!d || (!d.suggestions.length && !d.looks_paid.length)) return null
  const tasks = new Map(ax.tasks.map(t => [t.id, t]))
  async function act(key: string, action: string, body: object, msg: string) {
    setBusy(key)
    try { await ax.act(action, body, ['tasks']); toast(msg); setEdit(null); await reloadBills() }
    catch (e: any) { toast.error(e.message) } finally { setBusy(null) }
  }
  return <section className="bg-card space-y-3 rounded-lg border p-4" data-bills-card="">
    <div className="flex items-center gap-2"><Receipt className="text-ink-3 size-4" /><span className="ax-label">Bills</span></div>
    {d.looks_paid.map(x => { const t = tasks.get(x.task_id); return t && <div key={x.id} className="flex flex-wrap items-center gap-2 text-sm" data-looks-paid="">
      <span className="min-w-0 flex-1">Looks paid: <b className="font-medium">{t.bill?.payee || t.text}</b> – a receipt for the same amount came in. Tick it off?</span>
      <Button size="pill" disabled={!!busy} onClick={() => act(x.id, 'bill_looks_paid', { id: x.id, on: true }, 'Bill ticked off as paid')}><Check />Paid</Button>
      <Button size="pill" variant="ghost" disabled={!!busy} onClick={() => act(x.id, 'bill_looks_paid', { id: x.id, on: false }, 'Kept as not paid')}>Not yet</Button>
    </div> })}
    {d.suggestions.map(c => edit === c.id
      ? <BillEdit key={c.id} c={c} reveal={!c.reference_hidden || shown.has(c.id)} busy={busy === c.id} onCancel={() => setEdit(null)}
          onSave={edits => act(c.id, 'bill_add', { id: c.id, edits, title: c.payee }, 'Bill added to To do')} />
      : <div key={c.id} className="space-y-1.5 border-t pt-3 first-of-type:border-0 first-of-type:pt-0" data-bill-suggestion="">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-medium">{c.payee || 'A bill'}</span>
          <span className="font-mono text-[14px] tabular-nums">{money(c.amount, c.currency)}</span>
          {c.due && <span className={cn('text-[13px]', c.due < new Date().toISOString().slice(0, 10) ? 'text-dawn' : 'text-ink-3')}>due {day(c.due)}</span>}
          {c.kind === 'reminder' && <span className="text-dawn text-[12px]">reminder</span>}
        </div>
        <BillWarning b={c} />
        {(!c.reference_hidden || shown.has(c.id)) ? <RefList r={c.reference} />
          : Object.keys(c.reference).length > 0 && <Button size="pill" variant="outline" data-show-details="" onClick={() => setShown(new Set([...shown, c.id]))}>Show payment details</Button>}
        <Source account={c.account} mid={c.message_id} subject={c.subject} attachments={c.attachments} />
        <div className="flex flex-wrap gap-2 pt-1">
          <Button size="pill" disabled={!!busy || !ax.apiOk} onClick={() => act(c.id, 'bill_add', { id: c.id, title: c.payee,
            ...(c.reference_hidden && shown.has(c.id) ? { edits: { reference: c.reference } } : {}) }, 'Bill added to To do')}><Check />Add to To do</Button>
          <Button size="pill" variant="outline" disabled={!!busy} onClick={() => setEdit(c.id)}><Pencil />Edit</Button>
          <Button size="pill" variant="outline" disabled={!!busy || !ax.apiOk} data-bill-paid-already="" onClick={() => act(c.id, 'bill_paid_already', { id: c.id, title: c.payee }, 'Marked as paid – it’s in Receipts as paid')}><CheckCheck />Already paid</Button>
          <Button size="pill" variant="ghost" disabled={!!busy || !ax.apiOk} onClick={() => act(c.id, 'bill_dismiss', { id: c.id, title: c.payee }, 'Not a bill – it won’t come back')}><X />Not a bill</Button>
        </div>
      </div>)}
    <p className="text-ink-3 text-[11.5px]">Found in your receipts and invoices. Axella never pays – tick a bill in To do when it's paid.</p>
  </section>
}

function BillEdit({ c, reveal, busy, onSave, onCancel }: { c: BillCard; reveal: boolean; busy: boolean; onSave: (e: Record<string, unknown>) => void; onCancel: () => void }) {
  const r: BillRef = reveal ? c.reference : {}     // hidden details are never prefilled – type them or tap Show first
  const [f, setF] = useState({ payee: c.payee || '', amount: c.amount == null ? '' : money(c.amount), currency: c.currency || 'DKK', due: c.due?.slice(0, 10) || '',
    fi: r.fi || '', iban: r.iban || '', account: r.account || '', mobilepay: r.mobilepay || '', invoice_no: r.invoice_no || '' })
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value })
  const field = (k: keyof typeof f, label: string, cls = '', type = 'text') => <label className={cn('block', cls)}><span className="text-ink-3 mb-0.5 block text-[12px]">{label}</span>
    <Input type={type} value={f[k]} onChange={set(k)} className={k !== 'payee' ? 'font-mono' : ''} /></label>
  return <form className="space-y-2 border-t pt-3" data-bill-edit="" onSubmit={e => { e.preventDefault()
    onSave({ payee: f.payee, amount: f.amount, currency: f.currency, due: f.due || null,
      reference: Object.fromEntries((['fi', 'iban', 'account', 'mobilepay', 'invoice_no'] as const).filter(k => f[k].trim()).map(k => [k, f[k].trim()])) }) }}>
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {field('payee', 'Payee', 'col-span-2')}{field('amount', 'Amount')}{field('currency', 'Currency')}
      {field('due', 'Due', '', 'date')}{field('fi', 'FI (+71<…)', 'col-span-2 sm:col-span-3')}
      {field('iban', 'IBAN', 'col-span-2')}{field('account', 'Reg. and account')}{field('mobilepay', 'MobilePay')}{field('invoice_no', 'Invoice no.')}
    </div>
    <div className="flex gap-2"><Button size="pill" type="submit" disabled={busy}><Check />Add to To do</Button><Button size="pill" type="button" variant="ghost" onClick={onCancel}>Cancel</Button></div>
  </form>
}

/** The safety notes on a bill card and its To do. */
export function BillWarning({ b }: { b: { first_time?: boolean; details_differ?: boolean; sender_differs?: boolean; payee?: string } }) {
  if (!b.first_time && !b.details_differ && !b.sender_differs) return null
  return <div className="text-dawn space-y-0.5 text-[13px]" data-bill-warning="">
    {b.first_time && <p>First bill from this sender – check the details with them before you pay.</p>}
    {b.sender_differs && <p>From another address than {b.payee || 'this payee'}’s earlier bills.</p>}
    {b.details_differ && <p>The payment details differ from {b.payee || 'this payee'}’s earlier bills.</p>}
  </div>
}

/** On a bill's To do row: amount (mono) in the meta line, and the payment details when the row is opened. */
export function BillMeta({ b }: { b: Bill }) {
  return <span className="font-mono tabular-nums" data-bill-amount="">{money(b.amount, b.currency)}</span>
}
export function BillDetails({ t }: { t: Task }) {
  const b = t.bill
  const d = useBills()               // the payment details come from bills.json on the Mac mini, not from the To do
  if (!b) return null
  return <div className="bg-bg-2/60 space-y-1.5 rounded-md p-2.5" data-bill-details="">
    <BillWarning b={b} />
    <RefList r={d?.refs?.[t.id] || {}} />
    {b.message_id && <Source account={b.account} mid={b.message_id} subject={b.subject} attachments={b.attachments || []} />}
    <p className="text-ink-3 text-[11.5px]">Tick it when it's paid – the receipt in Receipts is marked paid too.</p>
  </div>
}
