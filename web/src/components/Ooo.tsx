import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Check, Copy, ExternalLink, Loader2, Plane, Save, Wand2 } from '@/components/ax-icons'
import { SectionCard } from '@/components/Section'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { profile, type Account } from '@/lib/profile'
import { cn } from '@/lib/utils'

interface Box { text: string; internal: string; external: string; applied: string | null }
interface Ooo {
  from: string | null; until: string | null; active: boolean
  mailboxes: Record<string, Box>; accounts: Account[]
  voice: { on: boolean; da: string; en: string }
}
const area = 'border-line-strong bg-card focus-visible:border-ring focus-visible:ring-ring/30 w-full rounded-md border px-2.5 py-1.5 text-[16px] outline-none focus-visible:ring-2 sm:text-sm'
const en = (d: string) => new Date(d + 'T12:00').toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })
const da = (d: string) => new Date(d + 'T12:00').toLocaleDateString('da-DK', { weekday: 'long', day: 'numeric', month: 'long' })
function nextWorkday(d: string) {
  const x = new Date(d + 'T12:00'); do { x.setDate(x.getDate() + 1) } while (x.getDay() === 0 || x.getDay() === 6)
  return x.toISOString().slice(0, 10)
}
const isICloud = (a: Account) => /icloud/i.test(a.id)

function suggest(from: string, until: string, accounts: Account[]) {
  const o = profile().owner, first = o.first_name || 'me', sign = o.sign_off || 'Best regards', full = o.name || first
  const back = nextWorkday(until)
  const wpName = (a: Account) => profile().workplaces.find(w => w.id === a.workplace)?.name || a.label
  const boxes: Record<string, Partial<Box>> = {}
  for (const a of accounts) {
    boxes[a.id] = a.kind === 'work'
      ? { internal: `Hi\n\nI'm out of office from ${en(from)} until ${en(until)} and back on ${en(back)}. For anything urgent, please contact [name, e-mail].\n\n${sign}`,
          external: `Hello\n\nThank you for your message. I'm out of office until ${en(until)} and will reply after I'm back on ${en(back)}. For urgent matters, please contact [name, e-mail].\n\nBest regards\n${full}\n${wpName(a)}` }
      : { text: `Hej\n\nTak for din mail. Jeg er på ferie fra ${da(from)} til og med ${da(until)} og læser kun mail en gang imellem. Jeg vender tilbage, når jeg er hjemme igen.\n\n${sign}\n\n—\n\nHi\n\nThanks for your email. I'm on holiday from ${en(from)} until ${en(until)} and only check mail now and then. I'll get back to you when I'm home.\n\n${sign}` }
  }
  return {
    boxes,
    voice: {
      da: `Hej, du har ringet til ${full}. Jeg er Axella, ${first}s AI-assistent. ${first} er på ferie til og med ${da(until)}. Læg gerne en besked, så får ${first} den. You are also welcome to speak English.`,
      en: `Hi, you've reached ${full}. I'm Axella, ${first}'s AI assistant. ${first} is on holiday until ${en(until)}. Please leave a message and it will be passed on.`,
    },
  }
}

export function OutOfOfficeCard() {
  const { ax } = useApp()
  const [o, setO] = useState<Ooo | null>(null)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const load = () => get<Ooo>('ooo').then(r => { setO(r); setDirty(false) }).catch(() => {})
  useEffect(() => { load() }, [])
  if (!o) return null
  const vac = ax.schedule?.schedule.vacation
  const upd = (p: Partial<Ooo>) => { setO({ ...o, ...p }); setDirty(true) }
  const setBox = (acc: string, p: Partial<Box>) => upd({ mailboxes: { ...o.mailboxes, [acc]: { ...o.mailboxes[acc], ...p } } })
  const save = async (msg = 'Out of office saved') => {
    setBusy(true)
    const mailboxes = Object.fromEntries(Object.entries(o.mailboxes).map(([k, b]) => [k, { text: b.text, internal: b.internal, external: b.external }]))
    try { const r = await ax.act<{ result: Ooo }>('ooo_set', { from: o.from, until: o.until, mailboxes, voice: o.voice }, []); setO(r.result); setDirty(false); toast(msg) }
    catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(false) }
  }
  const mark = async (account: string, set: boolean) => {
    try { const r = await ax.act<{ result: Ooo }>('ooo_applied', { account, set }, []); setO(r.result) } catch (e: any) { toast.error('Failed: ' + e.message) }
  }
  const copy = (t: string, what: string) => navigator.clipboard.writeText(t).then(() => toast.success(what + ' copied'))
  const fill = () => {
    if (!o.from || !o.until) { toast.error('Set the dates first'); return }
    const s = suggest(o.from, o.until, o.accounts)
    const has = Object.values(o.mailboxes).some(b => b.text || b.internal || b.external) || o.voice.da || o.voice.en
    if (has && !confirm('Replace the current texts with suggestions?')) return
    const mb = { ...o.mailboxes }
    for (const [k, v] of Object.entries(s.boxes)) mb[k] = { ...mb[k], ...v }
    upd({ mailboxes: mb, voice: { ...o.voice, ...s.voice } })
  }
  const short = (d: string) => new Date(d + 'T12:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
  const sub = o.active ? 'Active now' : o.from && o.until ? `Planned ${short(o.from)} – ${short(o.until)}` : 'Not planned'
  const when = (iso: string | null) => iso ? 'Marked as set ' + new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : 'Mark as set'

  return (
    <SectionCard id="ooo" color="var(--ax-p3)" icon={Plane} title="Out of office" sub={sub}>
      <div className="space-y-4 p-4 text-sm">
        <p className="text-muted-foreground text-xs">Mail servers keep their own auto-replies and none can be switched from the Mac mini, so Axella keeps the period and one text per mailbox, gives you the text and the right settings page, and reminds you the evening before and the morning after. The call agent switches to the away greeting on its own.</p>
        <div className="grid grid-cols-2 gap-2">
          <label className="space-y-1"><span className="text-muted-foreground text-xs">From</span>
            <Input type="date" value={o.from || ''} onChange={e => upd({ from: e.target.value || null })} /></label>
          <label className="space-y-1"><span className="text-muted-foreground text-xs">Until (last day away)</span>
            <Input type="date" value={o.until || ''} min={o.from || undefined} onChange={e => upd({ until: e.target.value || null })} /></label>
        </div>
        <div className="flex flex-wrap gap-2">
          {vac?.from && vac?.until && (vac.from !== o.from || vac.until !== o.until) &&
            <Button size="sm" variant="outline" onClick={() => upd({ from: vac.from, until: vac.until })}>Use vacation dates</Button>}
          <Button size="sm" variant="outline" onClick={fill}><Wand2 />Suggest texts</Button>
        </div>

        {o.accounts.map(a => {
          const b = o.mailboxes[a.id] || { text: '', internal: '', external: '', applied: null }
          return a.kind === 'work'
            ? <Block key={a.id} title={`Work – ${a.label}`} applied={b.applied} onMark={s => mark(a.id, s)} label={when(b.applied)}
                steps={<>On the Mac: Mail → right-click the {a.label} <b>Inbox</b> → <b>Get Account Info</b> → <b>Out of Office</b> → “While scheduled”, set the dates, paste both texts (Exchange / Microsoft 365). Or your mail provider's web settings, e.g. Outlook on the web → Settings → Account → <b>Automatic replies</b>.</>}
                links={[['Open Outlook on the web', 'https://outlook.office.com/mail/']]}>
                <div className="text-muted-foreground text-xs">Inside {a.label}</div>
                <Text v={b.internal} on={v => setBox(a.id, { internal: v })} onCopy={() => copy(b.internal, 'Internal text')} rows={4} />
                <div className="text-muted-foreground text-xs">Outside {a.label}</div>
                <Text v={b.external} on={v => setBox(a.id, { external: v })} onCopy={() => copy(b.external, 'External text')} rows={5} />
              </Block>
            : <Block key={a.id} title={`Private – ${a.label}`} applied={b.applied} onMark={s => mark(a.id, s)} label={when(b.applied)}
                steps={isICloud(a)
                  ? <>iCloud.com → Mail → Settings (gear) → <b>Auto-Reply</b> → tick “Automatically reply”, paste the text, set the same dates. iCloud replies once per sender per 24 h and stops by itself after the end date.</>
                  : <>Your mail provider's web settings → auto-reply / vacation responder: paste the text and set the same dates.</>}
                links={isICloud(a) ? [['Open iCloud Mail', 'https://www.icloud.com/mail/']] : []}>
                <Text v={b.text} on={v => setBox(a.id, { text: v })} onCopy={() => copy(b.text, a.label + ' text')} rows={7} />
              </Block>
        })}

        <div className="space-y-2 rounded-lg border p-3">
          <label className="flex items-center gap-2 font-medium">
            <Checkbox checked={o.voice.on} onCheckedChange={c => upd({ voice: { ...o.voice, on: !!c } })} />Call agent: away greeting during the period</label>
          <p className="text-muted-foreground text-xs">Switches on and off by itself on the dates (within a minute). It still takes a message. Everyone who calls hears it, strangers too – say <i>that</i> you're unavailable, not where or until when. A greeting left empty uses your normal greeting{o.voice.on && !o.voice.da.trim() && !o.voice.en.trim() ? ' – right now both are empty, so callers hear the normal one' : ''}.</p>
          <div className={cn('space-y-2', !o.voice.on && 'opacity-60')}>
            <textarea rows={3} className={area} value={o.voice.da} placeholder="Danish away greeting – empty = your normal greeting" onChange={e => upd({ voice: { ...o.voice, da: e.target.value } })} />
            <textarea rows={3} className={area} value={o.voice.en} placeholder="English away greeting – empty = your normal greeting" onChange={e => upd({ voice: { ...o.voice, en: e.target.value } })} />
          </div>
        </div>

        {dirty && <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={load}>Undo changes</Button>
          <Button size="sm" onClick={() => save()} disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <Save />}Save</Button>
        </div>}
      </div>
    </SectionCard>
  )
}

function Block({ title, steps, links, children, applied, onMark, label }: {
  title: string; steps: React.ReactNode; links: [string, string][]; children: React.ReactNode
  applied: string | null; onMark: (set: boolean) => void; label: string
}) {
  return (
    <div className="space-y-2 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{title}</span>
        <label className={cn('flex items-center gap-1.5 text-xs', applied ? 'text-success' : 'text-muted-foreground')}>
          <Checkbox checked={!!applied} onCheckedChange={c => onMark(!!c)} />{applied && <Check className="size-3.5" />}{label}</label>
      </div>
      {children}
      <p className="text-muted-foreground text-xs">{steps}</p>
      {!!links.length && <div className="flex flex-wrap gap-2">{links.map(([l, u]) =>
        <Button key={u} size="sm" variant="outline" asChild><a href={u} target="_blank" rel="noopener noreferrer"><ExternalLink />{l}</a></Button>)}</div>}
    </div>
  )
}

function Text({ v, on, onCopy, rows }: { v: string; on: (v: string) => void; onCopy: () => void; rows: number }) {
  return <div className="relative">
    <textarea rows={rows} className={area + ' pr-10'} value={v} onChange={e => on(e.target.value)} placeholder="Tap “Suggest texts” or write your own" />
    <button type="button" aria-label="Copy" title="Copy" disabled={!v} onClick={onCopy}
      className="text-muted-foreground hover:text-foreground absolute top-1.5 right-1.5 rounded p-1 disabled:opacity-40"><Copy className="size-4" /></button>
  </div>
}
