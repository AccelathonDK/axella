/* Backup and move (setup/backup.py): Settings → System → Backup. Export one encrypted file (a passphrase you choose,
   asked twice, never stored), automatic weekly backups to a folder you pick (passphrase in the Keychain only, keep
   4), and how to restore. Keys and tokens are never in a backup – they're listed to reconnect after a restore. */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { AlertTriangle, Archive, Check, Loader2, Upload } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'

interface Auto { on: boolean; folder: string | null; history: boolean; last_ok: string | null; last_try: string | null; last_error: string | null; last_name: string | null; icloud: boolean; keep: number }
interface BV { age: boolean; auto: Auto; reconnect: string[]; left_out: string[]; min_pass: number; keep: number }
interface Exported { id: string; name: string; size: number; files: number; history: boolean }

const mb = (n: number) => n < 1e6 ? Math.max(1, Math.round(n / 1e3)) + ' KB' : (n / 1e6).toFixed(1) + ' MB'
const when = (s: string | null) => s ? new Date(s).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '–'

export function BackupCard() {
  const { ax } = useApp()
  const [v, setV] = useState<BV | null>(null)
  const load = () => get<BV>('backup').then(r => setV((r as any).auto ? r : null)).catch(() => setV(null))
  useEffect(() => { if (ax.apiOk) load() }, [ax.apiOk])
  if (!v) return null
  return <div className="bg-card divide-y overflow-hidden rounded-lg border" data-backup="">
    <div className="px-4 py-2.5"><div className="flex items-center gap-2 font-semibold"><Archive className="text-ink-3 size-4" />Backup</div>
      <div className="text-ink-3 text-[12.5px]">Everything Axella has learned in one encrypted file – to keep, or to move to a new Mac mini. Axella never uploads a backup anywhere itself.</div></div>
    {!v.age && <div className="bg-dawn/15 flex gap-2 px-4 py-2.5 text-[13px]"><AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span>The encryption tool is missing on the Mac mini. In Terminal there: <code className="font-mono">brew install age</code> (version 1.3 or later).</span></div>}
    <ExportPart v={v} />
    <AutoPart v={v} reload={load} />
    <div className="space-y-1.5 px-4 py-3 text-[13px]" data-tour="backup-restore">
      <div className="font-semibold">Restore</div>
      <p className="text-ink-2">On the new (or the same) Mac mini: install Axella, copy the file over, stop the Axella service, then in Terminal in the Axella folder run <code className="font-mono">tools/restore.sh &lt;file&gt;</code>. It first shows what's in the backup and what would be replaced. Add <code className="font-mono">--apply</code> to restore: the current data is moved aside, never deleted.</p>
      <details><summary className="text-fjord cursor-pointer font-semibold">What you reconnect after a restore</summary>
        <ul className="text-ink-2 mt-1 list-disc space-y-0.5 pl-5">{v.reconnect.map(r => <li key={r}>{r}</li>)}</ul>
        <p className="text-ink-3 mt-1">Keys and tokens are never in a backup – they belong to one Mac and are made again.</p></details>
    </div>
  </div>
}

function Passphrase({ min, a, b, setA, setB }: { min: number; a: string; b: string; setA: (s: string) => void; setB: (s: string) => void }) {
  return <div className="grid gap-2 sm:grid-cols-2">
    <Input type="password" autoComplete="new-password" placeholder={`Passphrase (at least ${min} characters)`} value={a} onChange={e => setA(e.target.value)} aria-label="Passphrase" />
    <Input type="password" autoComplete="new-password" placeholder="The same once more" value={b} onChange={e => setB(e.target.value)} aria-label="Passphrase again" />
    <PassHint min={min} a={a} b={b} />
  </div>
}

/* Why the button is still off – type the passphrase in both fields (a password manager often fills only the first) */
function PassHint({ min, a, b }: { min: number; a: string; b: string }) {
  const left = min - a.length
  const [text, tone] = !a ? [`Type a passphrase of at least ${min} characters in both fields – the button turns on when they match.`, 'text-ink-3']
    : left > 0 ? [`${left} more character${left === 1 ? '' : 's'} – at least ${min}.`, 'text-ink-3']
    : !b ? ['Now type it once more in the second field (a password manager often fills only the first).', 'text-ink-3']
    : a !== b ? ['The two passphrases are not the same.', 'text-danger']
    : ['The passphrases match.', 'text-fjord']
  return <div className={tone + ' text-[12.5px] sm:col-span-2'} aria-live="polite" data-pass-hint="">{text}</div>
}

function ExportPart({ v }: { v: BV }) {
  const { ax } = useApp()
  const [a, setA] = useState(''), [b, setB] = useState(''), [hist, setHist] = useState(false)
  const [busy, setBusy] = useState(false), [done, setDone] = useState<Exported | null>(null)
  const ready = v.age && a.length >= v.min_pass && a === b
  async function go() {
    setBusy(true)
    try {
      const r: any = await ax.act('backup_export', { passphrase: a, again: b, history: hist, title: 'Export backup' }, [])
      setDone(r.result); setA(''); setB('')
    } catch (e: any) { toast.error('Not exported: ' + e.message) } finally { setBusy(false) }
  }
  return <div className="space-y-2.5 px-4 py-3 text-sm" data-backup-export="">
    <div className="font-semibold">Export backup</div>
    {done ? <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3"><Check className="text-fjord size-4" /><span className="font-mono text-[13px]">{done.name}</span><span className="text-ink-3">{mb(done.size)} · {done.files} files{done.history ? ' · with history' : ''}</span></div>
      <div className="flex flex-wrap items-center gap-3">
        <Button size="pill" asChild><a href={'api/backup_download?id=' + done.id} download={done.name} onClick={() => setTimeout(() => setDone(null), 1500)}><Upload className="rotate-180" />Download</a></Button>
        <span className="text-ink-3 text-[12.5px]">One download, within an hour. Keep the passphrase safe – without it the backup can't be opened.</span></div>
    </div> : <>
      <Passphrase min={v.min_pass} a={a} b={b} setA={setA} setB={setB} />
      <label className="flex items-center gap-2 text-[13px]" data-tour="backup-history"><input type="checkbox" checked={hist} onChange={e => setHist(e.target.checked)} />Include history – digests, calls, the activity log and recordings (larger, and personal)</label>
      <div className="flex flex-wrap items-center gap-3">
        <Button size="pill" disabled={!ready || busy} onClick={go}>{busy ? <Loader2 className="animate-spin" /> : <Archive />}{busy ? 'Encrypting…' : 'Export backup'}</Button>
        <span className="text-ink-3 text-[12.5px]">The passphrase is never stored. Lose it and the backup is lost too.</span></div>
    </>}
  </div>
}

function AutoPart({ v, reload }: { v: BV; reload: () => void }) {
  const { ax } = useApp()
  const s = v.auto
  const [folder, setFolder] = useState(s.folder || ''), [a, setA] = useState(''), [b, setB] = useState(''), [hist, setHist] = useState(s.history)
  const [busy, setBusy] = useState<string | null>(null)
  const act = async (k: string, action: string, body: Record<string, unknown>, ok: string) => {
    setBusy(k)
    try { await ax.act(action, body, []); toast(ok); setA(''); setB(''); reload() }
    catch (e: any) { toast.error(e.message); reload() } finally { setBusy(null) }
  }
  if (s.on) return <div className="space-y-2 px-4 py-3 text-sm" data-backup-auto="on">
    <div className="font-semibold">Automatic weekly backups · on</div>
    <dl className="text-[13px]">
      <div className="flex gap-3 py-0.5"><dt className="text-ink-3 w-28 shrink-0">Folder</dt><dd className="min-w-0 font-mono text-[12.5px] break-all">{s.folder}</dd></div>
      <div className="flex gap-3 py-0.5"><dt className="text-ink-3 w-28 shrink-0">Last backup</dt><dd>{when(s.last_ok)}{s.last_name ? ` · ${s.last_name}` : ''}</dd></div>
      <div className="flex gap-3 py-0.5"><dt className="text-ink-3 w-28 shrink-0">Kept</dt><dd>The last {s.keep}{s.history ? ' · with history' : ''}</dd></div>
    </dl>
    {s.last_error && <div className="text-danger text-[13px]">Last try failed: {s.last_error}</div>}
    {s.icloud && <div className="text-ink-2 text-[12.5px]">This folder is in iCloud Drive, so Apple keeps a copy in iCloud – your choice. The file is encrypted with your passphrase.</div>}
    <div className="flex flex-wrap gap-2">
      <Button size="pill" disabled={!!busy || !v.age} onClick={() => act('run', 'backup_run', { title: 'Back up now' }, 'Backed up')}>{busy === 'run' ? <Loader2 className="animate-spin" /> : <Archive />}Back up now</Button>
      <Button size="pill" variant="outline" disabled={!!busy} onClick={() => act('off', 'backup_auto', { on: false, title: 'Automatic backups off' }, 'Automatic backups off – the passphrase is removed from the Keychain')}>Turn off</Button>
    </div>
  </div>
  const ready = v.age && folder.trim() && a.length >= v.min_pass && a === b
  return <div className="space-y-2.5 px-4 py-3 text-sm" data-backup-auto="off">
    <div className="font-semibold">Automatic weekly backups · off</div>
    <p className="text-ink-3 text-[12.5px]">Once a week to a folder on the Mac mini you pick – an external disk, a NAS share or an iCloud Drive folder. The last {v.keep} are kept. The passphrase is kept in the Mac mini's Keychain while this is on.</p>
    <Input value={folder} onChange={e => setFolder(e.target.value)} placeholder="/Volumes/Backup/Axella" aria-label="Folder on the Mac mini" className="font-mono text-[13px]" />
    <Passphrase min={v.min_pass} a={a} b={b} setA={setA} setB={setB} />
    <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={hist} onChange={e => setHist(e.target.checked)} />Include history</label>
    <Button size="pill" disabled={!ready || !!busy} onClick={() => act('on', 'backup_auto', { on: true, folder: folder.trim(), passphrase: a, again: b, history: hist, title: 'Automatic backups on' }, 'Automatic backups on – the first one runs within half an hour')}>
      {busy === 'on' ? <Loader2 className="animate-spin" /> : <Check />}Turn on</Button>
  </div>
}
