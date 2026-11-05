import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Archive, Check, Loader2, Undo2, X } from '@/components/ax-icons'
import { SectionCard } from '@/components/Section'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { accLabel, profile } from '@/lib/profile'
import { cn } from '@/lib/utils'

/* Mail cleanup (setup/cleanup.py): old mail with no relationship and no historical value → the account's "Cleanup"
   folder. Nothing is deleted; every batch can be undone. Mailboxes and age are chosen under Settings. */
export const CleanupIcon = Archive

interface Group { key: string; account: string; sender: string; name: string; domain: string; count: number; size: number
  oldest: string; newest: string; examples: string[]; folders: string[]; kind: 'automated' | 'other' }
interface Batch { id: string; kind: 'move' | 'undo'; status: 'queued' | 'running' | 'done' | 'failed' | 'undone'; created: string
  count: number; moved: number; label: string; error?: string | null; ended?: string }
interface CState {
  settings: { accounts: string[]; age_months: number; keep: string[]; all_folders: boolean; include_filed?: boolean }; ages: number[]; folder: string
  scan: { at: string; accounts: string[]; age_months: number; folders: number; mails: number; errors: string[]
    folders_detail?: { account: string; folder: string; old: number; candidates: number; kept: Record<string, number> }[] } | null
  scanning: boolean; groups: Group[]; total: number; size: number; batches: Batch[]
}

const mb = (n: number) => n > 1e9 ? (n / 1e9).toFixed(1) + ' GB' : n > 1e6 ? Math.round(n / 1e6) + ' MB' : Math.max(1, Math.round(n / 1e3)) + ' KB'
const ym = (d: string) => { const [y, m] = d.split('-').map(Number); return new Date(y, m - 1, 15).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' }) }
const when = (d?: string | null) => d ? new Date(d).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''

function useCleanup() {
  const [s, setS] = useState<CState | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const load = () => get<CState>('cleanup').then(x => { setS(x); setErr(null) }).catch(e => setErr(e.message))
  const busy = !!s && (s.scanning || s.batches.some(b => b.status === 'queued' || b.status === 'running'))
  useEffect(() => { load() }, [])
  useEffect(() => { const t = setInterval(load, busy ? 3000 : 30000); return () => clearInterval(t) }, [busy])
  return { s, err, load, busy }
}

export function CleanupView() {
  const { ax, go } = useApp()
  const { s, err, load } = useCleanup()
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState<string | null>(null)
  async function act(a: string, p: object, msg: string) {
    setBusy(a)
    try { await ax.act(a, p, []); toast(msg); await load() } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(null) }
  }
  if (!s) return <div className="text-muted-foreground py-10 text-center">{err ? 'Action service not reachable – ' + err : 'Loading…'}</div>
  const running = s.batches.find(b => b.status === 'queued' || b.status === 'running')
  const toggle = (k: string) => setSel(x => { const n = new Set(x); n.has(k) ? n.delete(k) : n.add(k); return n })
  const chosen = s.groups.filter(g => sel.has(g.key))
  const nChosen = chosen.reduce((a, g) => a + g.count, 0)
  const move = (keys: string[], n: number) => act('cleanup_move', { keys }, `Moving ${n} mail${n > 1 ? 's' : ''} to ${s.folder} – runs in the background`).then(() => setSel(new Set()))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1 basis-[18rem]">
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><CleanupIcon className="size-5" />Cleanup</h1>
          <p className="text-muted-foreground text-sm">Old mail with no relationship and no history worth keeping. Moving puts it in a “{s.folder}” folder in the same
            mailbox – nothing is deleted, and every move can be undone.</p>
        </div>
        <Button variant="outline" onClick={() => go({ kind: 'settings', page: 'mailbox' })}>Settings</Button>
      </div>

      {!s.settings.accounts.length ? <Card className="p-5 text-sm">Choose which mailboxes to clean up, and from what age, under
        <button className="text-fjord ml-1 underline-offset-2 hover:underline" onClick={() => go({ kind: 'settings', page: 'mailbox' })}>Settings → Mailbox</button>.</Card> : <>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Stat label="Could go" value={s.total.toLocaleString('da-DK')} sub={s.size ? mb(s.size) : ''} />
          <Stat label="Senders" value={String(s.groups.length)} />
          <Stat label="Older than" value={s.settings.age_months + ' months'} sub={s.settings.accounts.map(accLabel).join(', ')} className="col-span-2 sm:col-span-1" />
        </div>

        <div className="text-ink-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
          {s.scanning ? <span className="text-fjord inline-flex items-center gap-1.5"><Loader2 className="size-4 animate-spin" />Scanning your mail – this can take a few minutes</span>
            : s.scan ? <span>Last scan {when(s.scan.at)} · {s.scan.folders} folders{s.scan.errors.length ? ` · ${s.scan.errors.length} folder${s.scan.errors.length > 1 ? 's' : ''} skipped` : ''}</span>
            : <span>Not scanned yet.</span>}
          <Button size="pill" variant="outline" disabled={s.scanning || !!busy} onClick={() => act('cleanup_scan', {}, 'Scan started')}>Scan now</Button>
          <span>Scans also run every Sunday night.</span>
        </div>

        {s.scan && !s.scanning && <ScanDetails scan={s.scan} allFolders={s.settings.all_folders} />}

        {running && <Card className="flex items-center gap-3 px-4 py-3 text-sm">
          <Loader2 className="text-fjord size-4 animate-spin" />
          <div className="min-w-0 flex-1">{running.kind === 'undo' ? 'Moving back' : 'Moving to ' + s.folder}: {running.label}
            <div className="bg-bg-2 mt-1.5 h-1.5 overflow-hidden rounded-sm"><div className="bg-fjord h-full transition-[width] duration-[480ms]" style={{ width: Math.round(running.moved / Math.max(1, running.count) * 100) + '%' }} /></div></div>
          <span className="text-ink-3 font-mono text-[12px]">{running.moved}/{running.count}</span>
        </Card>}

        {s.groups.length > 0 && <Card className="overflow-hidden">
          <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
            <span className="text-sm font-medium">{sel.size ? `${sel.size} sender${sel.size > 1 ? 's' : ''} · ${nChosen} mails` : 'Pick senders, or move them one by one'}</span>
            <span className="flex-1" />
            {sel.size > 0 && <Button size="pill" disabled={!!busy || !!running} onClick={() => move([...sel], nChosen)}><Archive />Move {nChosen} to {s.folder}</Button>}
            {sel.size > 0 && <Button size="pill" variant="ghost" onClick={() => setSel(new Set())}>Clear</Button>}
            {!sel.size && <Button size="pill" variant="outline" onClick={() => setSel(new Set(s.groups.filter(g => g.kind === 'automated').map(g => g.key)))}>Select all automated</Button>}
          </div>
          <ul className="divide-y">
            {s.groups.map(g => <li key={g.key} className={cn('flex flex-wrap items-start gap-x-3 gap-y-2 px-4 py-3', sel.has(g.key) && 'bg-fjord-soft/40')}>
              <Checkbox className="mt-1" checked={sel.has(g.key)} onCheckedChange={() => toggle(g.key)} aria-label={'Select ' + g.name} />
              <div className="min-w-0 flex-1 basis-[14rem]">
                <div className="flex flex-wrap items-baseline gap-x-2"><span className="truncate font-medium">{g.name}</span>
                  {s.groups.some(x => x !== g && x.name === g.name) && <span className="text-ink-2 truncate font-mono text-[12px]">{g.sender}</span>}
                  <span className="text-ink-3 font-mono text-[12px]">{g.count} mail{g.count > 1 ? 's' : ''} · {mb(g.size)}</span></div>
                <div className="text-ink-3 truncate text-[12px]">{g.sender} · {accLabel(g.account)} · {g.folders.join(', ')} · {ym(g.oldest)}{g.oldest !== g.newest ? ' – ' + ym(g.newest) : ''}</div>
                {g.examples.length > 0 && <div className="text-ink-2 mt-0.5 truncate text-[13px]">{g.examples.map(e => '“' + e + '”').join(' · ')}</div>}
                <div className="text-ink-3 mt-0.5 text-[12px]">{g.kind === 'automated' ? 'Automated sender' : 'One-way mail'} · no reply or mail to them in the mailboxes Axella reads</div>
              </div>
              <div className="flex max-w-[45%] shrink-0 flex-wrap justify-end gap-1.5">
                <Button size="pill" variant="outline" disabled={!!busy || !!running} onClick={() => move([g.key], g.count)}><Archive />Move</Button>
                <Button size="pill" variant="ghost" disabled={!!busy} title="Never suggest this sender again" onClick={() => act('cleanup_keep', { sender: g.sender }, `${g.name} will be kept`)}><Check />Keep</Button>
                {g.domain && !FREEMAIL.test(g.domain) && <Button size="pill" variant="ghost" disabled={!!busy} title={'Never suggest anyone from ' + g.domain}
                  onClick={() => act('cleanup_keep', { sender: '@' + g.domain }, `Everything from ${g.domain} will be kept`)}>Keep @{g.domain}</Button>}
              </div>
            </li>)}
          </ul>
        </Card>}
        {!s.scanning && s.scan && !s.groups.length && <Card className="text-ink-2 flex items-center gap-2 px-4 py-3.5 text-sm"><Check className="text-success size-4" />Nothing to clean up – everything old is either answered, from people you know, or worth keeping.</Card>}

        {s.batches.filter(b => b.status !== 'queued' && b.status !== 'running').length > 0 && <Card className="overflow-hidden">
          <div className="border-b px-4 py-2.5 text-sm font-medium">History</div>
          <ul className="divide-y">{s.batches.filter(b => b.status !== 'queued' && b.status !== 'running').slice(0, 10).map(b =>
            <li key={b.id} className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm', b.status === 'undone' && 'opacity-60')}>
              <span className="min-w-0 flex-1 truncate">{b.label}</span>
              <span className="text-ink-3 font-mono text-[12px]">{b.moved}/{b.count} · {when(b.ended || b.created)}{b.status === 'undone' ? ' · undone' : b.status === 'failed' ? ' · failed' : ''}</span>
              {b.kind === 'move' && b.status === 'done' && <Button size="pill" variant="ghost" disabled={!!busy || !!running} onClick={() => act('cleanup_undo', { id: b.id }, 'Moving them back – runs in the background')}><Undo2 />Undo</Button>}
            </li>)}</ul>
        </Card>}
      </>}
    </div>
  )
}

const FREEMAIL = /^(gmail|googlemail|icloud|me|mac|hotmail|outlook|live|yahoo|proton(mail)?|pm|gmx|aol|mail)\.[a-z.]+$/i

/* What the last scan looked at: per folder how many old mails, how many could go, and why the rest were kept */
function ScanDetails({ scan, allFolders }: { scan: NonNullable<CState['scan']>; allFolders: boolean }) {
  const [open, setOpen] = useState(false)
  const det = scan.folders_detail || []
  const old = det.reduce((a, f) => a + f.old, 0)
  return <Card className="overflow-hidden">
    <button onClick={() => setOpen(!open)} aria-expanded={open} className="hover:bg-bg-2/50 flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm">
      <span className="min-w-0 flex-1">What the scan looked at: <span className="text-ink-2">{det.length} folder{det.length === 1 ? '' : 's'}, {old.toLocaleString('da-DK')} mails older than {scan.age_months} months</span>
        {!allFolders && <span className="text-ink-3"> · Inbox, Archive and notification folders only</span>}</span>
      <span className="text-fjord text-[13px]">{open ? 'Hide' : 'Details'}</span>
    </button>
    {open && <div className="ax-reveal border-t">
      <ul className="divide-y">{det.map(f => <li key={f.account + f.folder} className="px-4 py-2 text-[13px]">
        <div className="flex flex-wrap items-baseline gap-x-2"><span className="font-medium">{accLabel(f.account)} · {f.folder}</span>
          <span className="text-ink-3 font-mono text-[12px]">{f.old} old · {f.candidates} could go</span></div>
        {Object.keys(f.kept).length > 0 && <div className="text-ink-3">Kept: {Object.entries(f.kept).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k} ${n}`).join(' · ')}</div>}
      </li>)}</ul>
      {scan.errors.length > 0 && <div className="text-ink-2 border-t px-4 py-2 text-[12px]">Skipped: {scan.errors.join(' · ')}</div>}
      {!allFolders && <div className="text-ink-3 border-t px-4 py-2 text-[12px]">Old mail in your own folders isn't looked at – switch on “Look in my own folders and subfolders too” under Settings.</div>}
    </div>}
  </Card>
}

function Stat({ label, value, sub, className }: { label: string; value: string; sub?: string; className?: string }) {
  return <Card className={cn('px-4 py-3', className)}><div className="ax-label">{label}</div><div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
    {sub && <div className="text-ink-3 truncate text-[12px]">{sub}</div>}</Card>
}

/* Settings → Mailbox */
export function CleanupSettingsCard() {
  const { ax, go } = useApp()
  const { s, load } = useCleanup()
  const [busy, setBusy] = useState(false)
  if (!s || !ax.apiOk) return null
  async function save(p: object, msg: string, a = 'cleanup_settings') {
    setBusy(true)
    try { await ax.act(a, p, []); toast(msg); await load() } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(false) }
  }
  const accs = profile().accounts
  const on = new Set(s.settings.accounts)
  return (
    <SectionCard id="cleanup" icon={CleanupIcon} title="Mail cleanup" sub={`Old mail with no relationship → a “${s.folder}” folder · nothing is deleted`}
      right={<Button size="pill" variant="outline" onClick={() => go({ kind: 'mailbox', tab: 'cleanup' })}>Open</Button>}>
      <div className="space-y-4 p-4 text-sm">
        <div>
          <div className="mb-1.5 font-medium">Mailboxes</div>
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            {accs.map(a => <label key={a.id} className="inline-flex items-center gap-2">
              <Checkbox checked={on.has(a.id)} disabled={busy} onCheckedChange={v => {
                const next = v ? [...on, a.id] : [...on].filter(x => x !== a.id)
                save({ accounts: next }, v ? `${a.label} included in cleanup` : `${a.label} left out of cleanup`)
              }} />{a.label}{a.kind === 'work' && <span className="text-ink-3 text-[12px]">(work – check your employer's rules first)</span>}</label>)}
          </div>
        </div>
        <div>
          <div className="mb-1.5 font-medium">Older than</div>
          <ToggleGroup type="single" value={String(s.settings.age_months)} onValueChange={v => v && save({ age_months: Number(v) }, `Cleanup: mail older than ${v} months`)} aria-label="Age">
            {s.ages.map(a => <ToggleGroupItem key={a} value={String(a)}>{a} months</ToggleGroupItem>)}
          </ToggleGroup>
        </div>
        <label className="flex items-start gap-2">
          <Checkbox className="mt-0.5" checked={s.settings.all_folders} disabled={busy}
            onCheckedChange={v => save({ all_folders: !!v }, v ? 'Cleanup also looks in your own folders' : 'Cleanup looks in Inbox, Archive and notifications only')} />
          <span><span className="font-medium">Look in my own folders and subfolders too</span>
            <span className="text-ink-3 block text-[13px]">Every folder except Sent, Drafts, Trash, Junk and your receipt folders. The same rules apply, so mail you answered or from people you know stays. Off = only Inbox, Archive and notification folders.</span></span>
        </label>
        {s.settings.all_folders && <label className="flex items-start gap-2 pl-6">
          <Checkbox className="mt-0.5" checked={!!s.settings.include_filed} disabled={busy}
            onCheckedChange={v => save({ include_filed: !!v }, v ? 'Mail you filed yourself can be suggested too' : 'Mail you filed into your own folders is kept')} />
          <span><span className="font-medium">Also suggest mail I filed into my own folders</span>
            <span className="text-ink-3 block text-[13px]">Off: a mail you moved into a folder you named yourself is kept – filing it says it matters. Inbox, Archive and notification folders are always looked at.</span></span>
        </label>}
        <div className="text-ink-2 text-[13px] leading-relaxed">
          Never suggested: flagged mail, mail you replied to, people you wrote to or
          have in Contacts, receipts, project and knowledge mail, mail you filed into your own folders, authorities, banks, insurers,
          lawyers and accountants, and subjects like invoices, contracts, bookings, tickets, warranties, tax, accounts, company and
          property deals, claims, cases and payment reminders. Missing one? Tap Keep on the sender. Scans every Sunday night, or with “Scan now” on the Cleanup page.
        </div>
        {s.settings.keep.length > 0 && <div>
          <div className="mb-1.5 font-medium">Always kept <span className="text-ink-3 font-normal">({s.settings.keep.length})</span></div>
          <div className="flex flex-wrap gap-1.5">{s.settings.keep.map(k => <span key={k} className="bg-bg-2 inline-flex items-center gap-1 rounded-sm py-0.5 pr-1 pl-2 font-mono text-[12px]">{k}
            <button className="text-ink-3 hover:text-ink" title="Remove from the keep list" disabled={busy} onClick={() => save({ sender: k }, k + ' can be suggested again', 'cleanup_unkeep')}><X className="size-3.5" /></button></span>)}</div>
        </div>}
      </div>
    </SectionCard>
  )
}
