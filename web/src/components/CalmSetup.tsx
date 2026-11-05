/* Calm setup (setup/calm_setup.py): three steps, about two minutes, so the other apps stay quiet and Axella is the one
   voice. Steps 1 and 3 are instructions you follow and tick; step 2 (Axella's notifications on this device) is checked
   here by itself. Nothing on the iPhone is changed by Axella. Settings → Notifications → Calm setup always has it; a
   card shows once in Getting started (and on Today for a new installation) until done or dismissed – no reminders. */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Bell, BellOff, Check, ChevronRight, Loader2, Moon, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SectionCard } from '@/components/Section'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { bell, pushOn, registerSW } from '@/lib/push'
import { IOS, cn } from '@/lib/utils'
import { useVips } from '@/lib/vips'

interface CalmState { done: { banners: string | null; focus: string | null }; dismissed: string | null; new_install: boolean }

let cache: CalmState | null = null
const changed = () => window.dispatchEvent(new Event('ax-calm-setup'))
function useCalmSetup() {
  const { ax } = useApp()
  const [s, setS] = useState<CalmState | null>(cache)
  const [push, setPush] = useState<boolean | null>(null)
  useEffect(() => {
    if (!ax.apiOk) return
    let live = true
    const load = () => get<CalmState>('calm_setup').then(j => { if (j?.done && live) setS(cache = j) }).catch(() => {})
    const p = () => registerSW().then(() => pushOn()).then(v => live && setPush(v))
    load(); p()
    const h = () => { load(); p() }
    window.addEventListener('ax-calm-setup', h)
    return () => { live = false; window.removeEventListener('ax-calm-setup', h) }
  }, [ax.apiOk])
  const count = s ? (s.done.banners ? 1 : 0) + (push ? 1 : 0) + (s.done.focus ? 1 : 0) : 0
  return { s, push, count }
}

/* the full page: Settings → Notifications */
export function CalmSetupCard() {
  const { ax } = useApp()
  const { s, push, count } = useCalmSetup()
  const vips = useVips()
  const [busy, setBusy] = useState<string | null>(null)
  const where = IOS ? 'here' : 'on your iPhone'
  const Where = IOS ? 'Here' : 'On your iPhone'
  const people = [...new Set(vips.map(v => v.name.split(/\s+/)[0]).filter(Boolean))].slice(0, 12)
  async function tick(step: 'banners' | 'focus', on: boolean) {
    setBusy(step)
    try { await ax.act('calm_setup_step', { step, on, title: 'Calm setup' }, []); changed() }
    catch (e: any) { toast.error(e.message) } finally { setBusy(null) }
  }
  async function turnOn() {
    setBusy('push')
    try { toast(await bell(false)) } catch (e: any) { toast.error('Failed: ' + e.message) } finally { setBusy(null); changed() }
  }
  if (!s) return null
  const Step = ({ n, done, icon: I, title, why, children, action }: { n: number; done: boolean; icon: any; title: string; why: string; children: React.ReactNode; action: React.ReactNode }) =>
    <div className="flex gap-3 px-4 py-3.5" data-calm-step={n}>
      <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-md', done ? 'bg-fjord text-on-fjord' : 'bg-fjord-soft text-fjord')}>
        {done ? <Check className="size-[18px]" /> : <I className="size-[18px]" />}</span>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="text-[15px] font-semibold">{n}. {title}</div>
        <div className="text-ink-2 text-[14px] leading-relaxed">{children}</div>
        <div className="text-ink-3 text-[12.5px]">Why: {why}</div>
        <div className="pt-1">{action}</div>
      </div>
    </div>
  const doneBtn = (step: 'banners' | 'focus', done: boolean) => done
    ? <Button size="pill" variant="ghost" onClick={() => tick(step, false)} disabled={busy === step} className="text-fjord"><Check />Done<span className="text-ink-3 ml-1 font-normal">· undo</span></Button>
    : <Button size="pill" onClick={() => tick(step, true)} disabled={busy === step} data-calm-done={step}>{busy === step ? <Loader2 className="animate-spin" /> : <Check />}Done</Button>
  return <SectionCard id="calm-setup" icon={Moon} title="Calm setup" sub={count === 3 ? '3 of 3 done – the other apps stay quiet' : `${count} of 3 done · about 2 minutes`} count={null}>
    <div className="divide-y" data-calm-setup="" data-calm-count={count}>
      <Step n={1} done={!!s.done.banners} icon={BellOff} title="Turn off banners for Mail, Messages and WhatsApp"
        why="Axella tells you what matters, at the times you chose." action={doneBtn('banners', !!s.done.banners)}>
        {Where}: <b>Settings → Notifications → Mail</b> → turn off <b>Allow Notifications</b>. Or keep them in
        Notification Centre only: untick <b>Lock Screen</b> and <b>Banners</b>. Do the same for <b>Messages</b> and <b>WhatsApp</b>.
      </Step>
      <Step n={2} done={!!push} icon={Bell} title="Allow Axella's notifications"
        why="so urgent things still reach you." action={push
          ? <span className="text-fjord inline-flex items-center gap-1.5 text-[13px] font-semibold" data-calm-push="on"><Check className="size-4" />On for this device – Axella checked</span>
          : <Button size="pill" onClick={turnOn} disabled={busy === 'push'} data-calm-push="off">{busy === 'push' ? <Loader2 className="animate-spin" /> : <Bell />}Turn on notifications</Button>}>
        {push ? 'Axella can reach this device.' : IOS ? 'Open Axella from your Home Screen, then turn them on here.' : 'Turn them on in Axella on your iPhone (from the Home Screen) – and here too, if you like.'}
      </Step>
      <Step n={3} done={!!s.done.focus} icon={Moon} title="Create an “Axella” Focus"
        why="one switch for calm, which you can schedule for work hours." action={doneBtn('focus', !!s.done.focus)}>
        {Where}: <b>Settings → Focus → + → Custom</b>, name it <b>Axella</b>. Under <b>People</b>, allow the people you
        call urgent{people.length ? <> – your VIPs: {people.join(', ')}</> : ''}. Under <b>Apps</b>, allow <b>Axella</b>. Everything
        else stays silent. Add a schedule for your work hours if you like.
      </Step>
    </div>
    <div className="text-ink-3 border-t px-4 py-2.5 text-[12.5px]">Axella changes nothing {where} – these are steps you follow. Only step 2 is checked by Axella itself.</div>
  </SectionCard>
}

/* the card: once in Getting started, and on Today for a new installation – until it's done or dismissed */
export function CalmSetupNudge({ where, onOpen }: { where: 'guide' | 'today'; onOpen?: () => void }) {
  const { ax, go } = useApp()
  const { s, push, count } = useCalmSetup()
  const [busy, setBusy] = useState(false)
  if (!s || s.dismissed || push === null || count === 3 || (where === 'today' && !s.new_install)) return null
  async function dismiss() {
    setBusy(true)
    try { await ax.act('calm_setup_dismiss', { title: 'Calm setup' }, []); changed() } catch (e: any) { toast.error(e.message) } finally { setBusy(false) }
  }
  const open = () => { onOpen?.(); go({ kind: 'settings', page: 'notifications' }) }
  const inner = <div className="flex items-start gap-3">
    <span className="bg-fjord-soft text-fjord flex size-9 shrink-0 items-center justify-center rounded-md"><Moon className="size-[18px]" /></span>
    <div className="min-w-0 flex-1">
      <div className="text-[15px] font-semibold">Calm setup – 3 steps, about 2 minutes</div>
      <div className="text-ink-2 text-[13.5px]">Quiet Mail, Messages and WhatsApp on your iPhone, so Axella is the one voice.{count ? ` ${count} of 3 done.` : ''}</div>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button size="pill" onClick={open} data-calm-open=""><ChevronRight />{count ? 'Finish' : 'Start'}</Button>
        <Button size="pill" variant="ghost" onClick={dismiss} disabled={busy} data-calm-dismiss=""><X />Dismiss</Button>
      </div>
    </div>
  </div>
  return where === 'guide'
    ? <div className="bg-fjord-soft/30 mt-3 rounded-lg border p-3" data-calm-nudge="guide">{inner}</div>
    : <Card className="p-4" data-calm-nudge="today">{inner}</Card>
}
