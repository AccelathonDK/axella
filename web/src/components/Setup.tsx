/* The guided setup – "What should Axella handle?" (dev request claude/dev-request-guided-setup.md, sketch "Axella –
   Guided setup"): 1 About you · 2 the 7 cards · 3 one mini-setup per chosen card · 4 Summary. Every step can be left
   and resumed (progress saved per person); every card's setup has "Later – skip this one". Nothing is read before
   step 3 and nothing is ever sent; macOS permissions are only opened by your own tap. Invented examples only. */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { Check, Loader2, Plus } from '@/components/ax-icons'
import { MeetingServicesCard } from '@/components/CalendarInvites'
import { Diamond, Switch } from '@/components/Handles'
import { RecipientsCard } from '@/components/Settings'
import { openTour } from '@/components/Tour'
import { Button } from '@/components/ui/button'
import { Input, NativeSelect } from '@/components/ui/input'
import { get, post } from '@/lib/api'
import { useApp } from '@/lib/app'
import { featAct, featuresChanged, useFeatures, type CardId, type CardInfo, type FeaturesView } from '@/lib/features'
import { cn } from '@/lib/utils'

type Step = 'about' | 'cards' | CardId | 'summary'
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export function SetupView({ only }: { only?: CardId }) {
  const { ax, go } = useApp()
  const v = useFeatures(ax.apiOk)
  if (!ax.apiOk) return <p className="text-ink-3 text-sm">The setup needs the Mac mini – it isn't answering right now.</p>
  if (!v) return <p className="text-ink-3 text-sm">{v === null ? "The setup couldn't be loaded." : 'Loading…'}</p>
  if (only) return <OneCard v={v} card={only} onDone={() => { featuresChanged(); go({ kind: 'settings', page: 'handles' }) }} />
  return <Flow v={v} />
}

/** Settings → "Set up – n min": that card's mini-setup alone */
function OneCard({ v, card, onDone }: { v: FeaturesView; card: CardId; onDone: () => void }) {
  const c = v.cards.find(x => x.id === card)!
  const [ready, setReady] = useState(c.on)
  useEffect(() => {
    if (c.on) return
    featAct('card_set', { card, on: true, set_up: false, confirm: true }).then(() => setReady(true), e => toast.error(e.message))
  }, [card])          // eslint-disable-line react-hooks/exhaustive-deps
  if (!ready) return <p className="text-ink-3 text-sm">Switching {c.title} on…</p>
  return <Frame step={card} chosen={[card]}>
    <MiniSetup key={c.id + ':' + c.n_on} v={v} c={c} next={null} onNext={async skipped => { await featAct('setup_card', { card, skipped }); onDone() }} />
  </Frame>
}

function Flow({ v }: { v: FeaturesView }) {
  const { go } = useApp()
  const existing = !v.setup.needed
  const prog = v.setup.progress
  const initialChosen = useMemo<CardId[]>(() => prog?.chosen?.length ? prog.chosen
    : existing ? v.cards.filter(c => c.on).map(c => c.id) : v.cards.filter(c => c.default).map(c => c.id), [])   // eslint-disable-line react-hooks/exhaustive-deps
  const [chosen, setChosen] = useState<CardId[]>(initialChosen)
  const [queue, setQueue] = useState<CardId[]>([])
  const [skipped, setSkipped] = useState<CardId[]>(prog?.skipped || [])
  const resume = prog?.step && prog.step !== 'done' ? (prog.step.startsWith('card:') ? prog.step.slice(5) as CardId : prog.step as Step) : null
  const [step, setStep] = useState<Step>(resume || (v.owner && !existing ? 'about' : 'cards'))
  const save = (s: Step, extra: object = {}) => post('setup_save', { step: s === 'about' || s === 'cards' || s === 'summary' ? s : 'card:' + s, ...extra }).catch(() => {})
  const to = (s: Step, extra: object = {}) => { setStep(s); save(s, extra); window.scrollTo({ top: 0 }) }
  useEffect(() => { if (resume && resume !== 'about' && resume !== 'cards' && resume !== 'summary') setQueue(chosen.filter(c => !skipped.includes(c))) }, [])   // eslint-disable-line react-hooks/exhaustive-deps

  const confirmCards = async () => {
    // the confirmation: chosen cards on (marked "not set up" until their step is done), the rest off – data kept
    const turnOn = chosen.filter(id => !v.cards.find(c => c.id === id)!.on)
    const turnOff = v.cards.filter(c => c.on && !chosen.includes(c.id) && !c.owner_off).map(c => c.id)
    try {
      for (const id of turnOff) {
        let r = await featAct<any>('card_set', { card: id, on: false })
        if (r?.confirm) { if (!window.confirm(r.confirm)) return; r = await featAct('card_set', { card: id, on: false, confirm: true }) }
      }
      for (const id of turnOn) await featAct('card_set', { card: id, on: true, set_up: false, confirm: true })
    } catch (e: any) { toast.error(e.message); return }
    if (!v.owner) {                                          // others: steps 2 and 5 only
      await post('setup_save', { done: true }).catch(() => {})
      featuresChanged(); toast('Saved – these are your own choices'); go({ kind: 'settings', page: 'handles' }); return
    }
    const q = existing ? turnOn : chosen                    // a review sets up only what is new
    setQueue(q)
    to(q[0] || 'summary', { chosen })
  }
  const nextCard = (cur: CardId, skip: boolean) => {
    if (skip) setSkipped(s => [...s, cur])
    featAct('setup_card', { card: cur, skipped: skip }).catch(() => {})
    const i = queue.indexOf(cur)
    to(queue[i + 1] || 'summary', { skipped: skip ? [...skipped, cur] : skipped })
  }

  if (step === 'about') return <Frame step="about" chosen={chosen}><AboutYou v={v} onNext={() => to('cards')} /></Frame>
  if (step === 'cards') return <Frame step="cards" chosen={chosen}>
    <ChooseCards v={v} chosen={chosen} setChosen={setChosen} existing={existing} onBack={v.owner && !existing ? () => to('about') : undefined} onNext={confirmCards} />
  </Frame>
  if (step === 'summary') return <Frame step="summary" chosen={chosen}><Summary v={v} chosen={chosen} skipped={skipped} newInstall={!existing} /></Frame>
  const c = v.cards.find(x => x.id === step)!
  const i = queue.indexOf(step)
  return <Frame step={step} chosen={queue} idx={i}>
    <MiniSetup key={c.id + ':' + c.n_on} v={v} c={c} next={queue[i + 1] ? v.cards.find(x => x.id === queue[i + 1])!.title : null} onNext={skip => nextCard(step, skip)} />
  </Frame>
}

function Frame({ step, chosen, idx, children }: { step: Step; chosen: CardId[]; idx?: number; children: ReactNode }) {
  const n = ['about', 'cards'].includes(step) ? (step === 'about' ? 0 : 1) : step === 'summary' ? 3 : 2
  const labels = ['1 About you', '2 What to handle', `3 Set up${n === 2 && idx != null && idx >= 0 ? ` · ${idx + 1} of ${chosen.length}` : ''}`, '4 Summary']
  return <div className="mx-auto max-w-[1100px] space-y-6" data-setup={step}>
    <ol aria-label="Setup steps" className="flex flex-wrap gap-x-5 gap-y-2 font-mono text-[12px] tracking-[0.06em] uppercase">
      {labels.map((l, i) => <li key={l} aria-current={i === n ? 'step' : undefined} className={cn('flex items-center gap-2', i === n ? 'text-fjord font-medium' : i < n ? 'text-ink-2' : 'text-ink-3')}>
        <span aria-hidden className={cn('size-2 rotate-45', i <= n ? 'bg-current' : 'border-[1.5px] border-current')} />{l}</li>)}
    </ol>
    {children}
  </div>
}

const H = ({ title, sub }: { title: string; sub: string }) => <header className="space-y-2">
  <h1 className="text-[30px] leading-tight font-semibold tracking-[-0.02em] sm:text-[34px]">{title}</h1>
  <p className="text-ink-2 text-[16px] leading-relaxed">{sub}</p></header>
const Box = ({ title, children, ...rest }: { title?: string; children: ReactNode } & Record<string, unknown>) =>
  <section className="bg-card space-y-3 rounded-lg border p-5" {...rest}>{title && <h2 className="text-[18px] font-semibold">{title}</h2>}{children}</section>

/* ---------- 1 About you ---------- */
function AboutYou({ v, onNext }: { v: FeaturesView; onNext: () => void }) {
  const a = v.about
  const [name, setName] = useState(a?.name || '')
  const [lang, setLang] = useState<'en' | 'da'>(a?.language || 'en')
  const [days, setDays] = useState<number[]>(a?.work_hours.days || [0, 1, 2, 3, 4])
  const [from, setFrom] = useState(a?.work_hours.from || '08:30')
  const [until, setUntil] = useState(a?.work_hours.to || '16:30')
  const [digest, setDigest] = useState(a?.digest_time || '07:30')
  const [mode, setMode] = useState<'separate' | 'mixed' | 'private'>(a?.mode || 'separate')
  const [busy, setBusy] = useState(false)
  const next = async () => {
    setBusy(true)
    try { await post('setup_about', { name, language: lang, work_hours: { days, from, to: until }, digest_time: digest, mode }); onNext() }
    catch (e: any) { toast.error(e.message) } finally { setBusy(false) }
  }
  const modes = [['separate', 'Separate accounts for work and private', "You'll pick which account is which in the next steps."],
    ['mixed', 'Mixed – split by my work hours', 'Inside work hours Axella leans to work; outside, to private.'],
    ['private', 'Only private', 'No work scope at all.']] as const
  return <div className="mx-auto max-w-[760px] space-y-6">
    <H title="Hi. Let's set Axella up around your day." sub="A few things about you first. It takes about five minutes in all, and you can change everything later in Settings." />
    <Box>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-1.5 text-sm font-semibold">What should Axella call you?<Input value={name} onChange={e => setName(e.target.value)} placeholder="Alex" className="h-11 font-normal" /></label>
        <label className="space-y-1.5 text-sm font-semibold">Language<NativeSelect value={lang} onChange={e => setLang(e.target.value as 'en' | 'da')} className="h-11 w-full font-normal">
          <option value="en">English</option><option value="da">Dansk</option></NativeSelect></label>
        <div className="space-y-1.5 text-sm font-semibold">Work hours
          <div className="flex flex-wrap items-center gap-1.5 font-normal">{DAYS.map((d, i) => <button key={d} type="button" aria-pressed={days.includes(i)}
            onClick={() => setDays(days.includes(i) ? days.filter(x => x !== i) : [...days, i].sort())}
            className={cn('min-h-9 rounded-full border px-2.5 text-[13px]', days.includes(i) ? 'bg-ink text-bg border-ink' : 'bg-card')}>{d}</button>)}</div>
          <div className="flex items-center gap-2 font-normal"><Input value={from} onChange={e => setFrom(e.target.value)} aria-label="From" className="h-11 w-24 font-mono" />–
            <Input value={until} onChange={e => setUntil(e.target.value)} aria-label="To" className="h-11 w-24 font-mono" /></div></div>
        <label className="space-y-1.5 text-sm font-semibold">Morning digest at<Input value={digest} onChange={e => setDigest(e.target.value)} className="h-11 w-28 font-mono font-normal" /></label>
      </div>
      <fieldset className="space-y-2.5 border-t pt-5">
        <legend className="float-left mb-1 text-[16px] font-semibold">Work and private</legend>
        <p className="text-ink-2 clear-both text-sm">Axella keeps the two apart. How do your mail and messages look?</p>
        {modes.map(([id, t, s]) => <label key={id} className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3', mode === id && 'border-fjord bg-fjord-soft')}>
          <input type="radio" name="wp" checked={mode === id} onChange={() => setMode(id)} className="mt-1" />
          <span><span className="block font-semibold">{t}</span><span className="text-ink-2 block text-sm">{s}</span></span></label>)}
      </fieldset>
    </Box>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <span className="text-ink-3 text-sm">Nothing is read or sent yet.</span>
      <Button disabled={busy || !name.trim() || !days.length} onClick={next} data-setup-next="">{busy && <Loader2 className="animate-spin" />}Continue</Button>
    </div>
  </div>
}

/* ---------- 2 What should Axella handle? ---------- */
function ChooseCards({ v, chosen, setChosen, existing, onBack, onNext }: { v: FeaturesView; chosen: CardId[]; setChosen: (c: CardId[]) => void
  existing: boolean; onBack?: () => void; onNext: () => void }) {
  const [busy, setBusy] = useState(false)
  const name = v.about?.name?.split(' ')[0]
  const min = v.cards.filter(c => chosen.includes(c.id) && (!existing || !c.on)).reduce((s, c) => s + c.minutes, 0)
  return <div className="space-y-6">
    <H title={`What should Axella handle for you${name ? ', ' + name : ''}?`}
      sub={existing ? 'Everything that is on now is ticked. Untick what you don’t want – its work stops and its data is kept. Nothing changes until you confirm.'
        : 'Pick what you want help with. Start small if you like – you can add more any time, and each one is set up on its own.'} />
    <div className="grid gap-4 md:grid-cols-2">{v.cards.map(c => {
      const on = chosen.includes(c.id)
      return <article key={c.id} className={cn('bg-card space-y-2.5 rounded-lg p-5', on ? 'border-fjord border-2' : 'm-px border')} data-setup-card={c.id}>
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5"><Diamond color={c.color} /><h2 className="text-[19px] font-semibold">{c.title}</h2></div>
          {c.owner_off ? <span className="text-ink-3 text-[12.5px]">Switched off by the owner</span>
            : <Switch on={on} label={c.title} onChange={x => setChosen(x ? [...chosen, c.id] : chosen.filter(i => i !== c.id))} data-setup-switch={c.id} />}
        </div>
        <p className="text-[15px] leading-relaxed">{c.line}</p>
        <p className="text-ink-2 text-[13px] leading-relaxed">{c.includes}</p>
        <div className="text-ink-2 flex flex-wrap gap-x-4 gap-y-1 border-t pt-2.5 font-mono text-[12px] tracking-[0.03em] uppercase">
          <span>Needs · {c.needs}</span><span>Claude · {c.claude}</span></div>
      </article>
    })}</div>
    <section className="bg-bg-2 space-y-1 rounded-lg border px-5 py-4"><div className="ax-label">Always included</div><p className="text-sm">{v.core}.</p></section>
    <div className="flex flex-wrap items-center justify-between gap-3">
      {onBack ? <button className="text-fjord min-h-11 font-semibold" onClick={onBack}>Back</button> : <span />}
      <div className="flex flex-wrap items-center gap-4">
        <span className="text-ink-2 text-sm">{chosen.length} of 8 chosen{min ? ` · about ${min}–${min * 2} min to set up` : ''}</span>
        <Button disabled={busy} onClick={async () => { setBusy(true); try { await onNext() } finally { setBusy(false) } }} data-setup-next="">
          {busy && <Loader2 className="animate-spin" />}{v.owner ? (min ? 'Set these up' : 'Continue') : 'Save my choices'}</Button>
      </div>
    </div>
  </div>
}

/* ---------- 3 One card at a time ---------- */
function MiniSetup({ v, c, next, onNext }: { v: FeaturesView; c: CardInfo; next: string | null; onNext: (skipped: boolean) => Promise<void> | void }) {
  const [feat, setFeat] = useState<string[]>(() => { const on = c.features.filter(id => v.features[id].on); return on.length ? on : c.features.filter(id => !v.features[id].owner_off) })
  const [busy, setBusy] = useState(false)
  const [save, setSave] = useState<(() => Promise<void>) | null>(null)
  const go = async () => {
    setBusy(true)
    try {
      if (save) await save()
      const off = c.features.filter(id => !feat.includes(id) && v.features[id].on)
      const on = feat.filter(id => !v.features[id].on)
      for (const id of off) await featAct('feature_set', { id, on: false, confirm: true })
      for (const id of on) await featAct('feature_set', { id, on: true, confirm: true })
      await onNext(false)
    } catch (e: any) { toast.error(e.message) } finally { setBusy(false) }
  }
  const sub: Record<CardId, string> = {
    messages: 'Axella only reads. It never sends anything without your tap.', calendar: 'Which calendars are work and which are private – and how online meetings are made.',
    projects: 'Axella gathers mail into projects and suggests what to work on. You confirm every project it suggests.', trips: 'Axella finds bookings in your mail and builds a page per trip.',
    money: 'Receipts and invoices, bills, subscriptions and renewals – suggestions you confirm.', briefs: 'A few topics to follow on the web. Only the topic goes into the searches.',
    voice: 'Listen to your digest, and – later – a call agent for the calls you miss.',
  }
  const titles: Record<CardId, string> = {
    messages: 'Which mail and messages should Axella read?', calendar: 'Your calendars and meetings', projects: 'Projects and planning', trips: 'Trips',
    money: 'Money at home', briefs: 'Topic briefs and knowledge', voice: 'Voice',
  }
  return <div className="mx-auto max-w-[860px] space-y-5">
    <header className="space-y-2">
      <span className="inline-flex items-center gap-2 font-mono text-[12px] tracking-[0.08em] uppercase" style={{ color: c.color }}><Diamond color={c.color} size={8} />{c.title}{next ? ` · next: ${next}` : ''}</span>
      <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.02em] sm:text-[30px]">{titles[c.id]}</h1>
      <p className="text-ink-2 text-[16px]">{sub[c.id]}</p>
    </header>
    {c.id === 'messages' && <MessagesSetup setSave={setSave} />}
    {c.id === 'calendar' && <CalendarSetup setSave={setSave} />}
    {c.id === 'money' && <Box title="Bookkeeping"><p className="text-ink-2 text-sm">Where receipts and invoices may be forwarded – a closed list. Nothing is forwarded until you say so.</p><RecipientsCard /></Box>}
    {c.id === 'briefs' && <BriefsSetup setSave={setSave} />}
    {c.id === 'trips' && <TripsSetup setSave={setSave} />}
    {c.id === 'voice' && <Box title="The call agent"><p className="text-ink-2 text-sm">The call agent needs a phone number of its own and a small service on the web. Leave it off now and set it up later in Settings → Calls – the spoken digest works without it.</p></Box>}
    <Box title={c.id === 'messages' ? 'What Axella does with them' : 'What Axella does'} data-setup-features="">
      <div className="grid gap-x-5 gap-y-1 sm:grid-cols-2">{c.features.map(id => { const f = v.features[id]
        return <label key={id} className="flex min-h-11 items-start gap-2.5 text-[15px]">
          <input type="checkbox" className="mt-1 size-4" checked={feat.includes(id)} disabled={f.owner_off}
            onChange={e => setFeat(e.target.checked ? [...feat, id] : feat.filter(x => x !== id))} />
          <span><span>{f.label}</span><span className="text-ink-3 block text-[12.5px]">{f.desc}</span></span></label> })}</div>
    </Box>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <button className="text-fjord min-h-11 font-semibold" onClick={() => onNext(true)} data-setup-skip="">Later – skip this one</button>
      <Button disabled={busy || !feat.length} onClick={go} data-setup-next="">{busy && <Loader2 className="animate-spin" />}{next ? `Continue to ${next}` : 'Continue'}</Button>
    </div>
  </div>
}

interface Sources { accounts: { name: string; label: string; read: boolean; kind: 'work' | 'private'; found: boolean }[]; calendars: { name: string; kind: 'work' | 'private' | 'ignore'; found: boolean }[]
  channels: { imessage: boolean; whatsapp: boolean; signal: boolean }; whatsapp_connected: boolean; signal_linked: boolean; lookback: 7 | 14 | 30 }

function useSources() {
  const [s, setS] = useState<Sources | null>(null)
  useEffect(() => { get<Sources>('setup_sources').then(setS, () => setS(null)) }, [])
  return [s, setS] as const
}

function MessagesSetup({ setSave }: { setSave: (f: () => () => Promise<void>) => void }) {
  const [s, setS] = useSources()
  const [msgOk, setMsgOk] = useState<string | null>(null)
  const check = () => get<{ checks?: { id: string; state: string; detail?: string }[] }>('system_status').then(r => {
    const c = (r.checks || []).find(x => x.id === 'imessage'); setMsgOk(c ? c.state : null)
  }, () => setMsgOk(null))
  useEffect(() => { check() }, [])
  useEffect(() => { if (s) setSave(() => async () => { await post('setup_sources_save', { accounts: s.accounts, channels: s.channels, lookback: s.lookback }) }) }, [s])   // eslint-disable-line react-hooks/exhaustive-deps
  if (!s) return <p className="text-ink-3 text-sm">Looking for your mail accounts…</p>
  const upd = (i: number, p: Partial<Sources['accounts'][0]>) => setS({ ...s, accounts: s.accounts.map((a, j) => j === i ? { ...a, ...p } : a) })
  const ch = (k: keyof Sources['channels'], val: boolean) => setS({ ...s, channels: { ...s.channels, [k]: val } })
  return <>
    <Box title="Mail accounts on this Mac" data-setup-accounts="">
      {s.accounts.length ? <ul className="divide-y">{s.accounts.map((a, i) => <li key={a.name} className="flex min-h-11 flex-wrap items-center gap-3 py-2.5">
        <input type="checkbox" className="size-[18px]" checked={a.read} onChange={e => upd(i, { read: e.target.checked })} aria-label={'Read ' + a.label} />
        <span className={cn('min-w-60 flex-1 font-mono text-[14px]', !a.read && 'text-ink-2')}>{a.label}</span>
        {a.read ? <NativeSelect value={a.kind} onChange={e => upd(i, { kind: e.target.value as 'work' | 'private' })} aria-label={'Work or private: ' + a.label} className="h-10 w-auto">
          <option value="work">Work</option><option value="private">Private</option></NativeSelect> : <span className="text-ink-3 text-[13px]">Not read</span>}
      </li>)}</ul> : <p className="text-ink-3 text-sm">No accounts found in Mail on this Mac yet – add them in Mail, then come back here (Settings → What Axella handles).</p>}
    </Box>
    <Box title="Messages">
      <ul className="divide-y">
        <li className="flex min-h-11 flex-wrap items-center gap-3 py-2.5"><input type="checkbox" className="size-[18px]" checked={s.channels.imessage} onChange={e => ch('imessage', e.target.checked)} aria-label="iMessage and SMS" />
          <span className="flex-1 font-semibold">iMessage and SMS</span><span className="font-mono text-[12px] tracking-[0.06em] uppercase">{msgOk === 'ok' ? 'Allowed' : msgOk ? 'Not allowed yet' : ''}</span></li>
        <li className="flex min-h-11 flex-wrap items-center gap-3 py-2.5"><input type="checkbox" className="size-[18px]" checked={s.channels.whatsapp} onChange={e => ch('whatsapp', e.target.checked)} aria-label="WhatsApp" />
          <span className="flex-1 font-semibold">WhatsApp</span><span className="text-ink-3 text-[13px]">{s.whatsapp_connected ? 'Connected' : 'Connect WhatsApp Desktop on this Mac – see SETUP.md'}</span></li>
        <li className="flex min-h-11 flex-wrap items-center gap-3 py-2.5"><input type="checkbox" className="size-[18px]" checked={s.channels.signal} onChange={e => ch('signal', e.target.checked)} aria-label="Signal" />
          <span className="flex-1 font-semibold">Signal</span><span className="text-ink-3 text-[13px]">{s.signal_linked ? 'Linked' : 'Not linked – Settings → Privacy'}</span></li>
      </ul>
      {msgOk !== 'ok' && <div className="bg-fjord-soft flex flex-wrap items-center gap-3 rounded-md px-4 py-3.5" data-setup-permission="">
        <span className="min-w-72 flex-1 text-sm leading-relaxed"><b>One permission needed:</b> Full Disk Access for Axella, so it can read Messages. Open it on the Mac mini (System Settings → Privacy &amp; Security → Full Disk Access); macOS asks once.</span>
        <Button size="sm" variant="outline" onClick={check}>Check again</Button>
      </div>}
    </Box>
    <Box>
      <div className="flex flex-wrap items-center gap-3">
        <span className="min-w-64 flex-1 text-[15px]">Look back how far for the first digest?</span>
        <div role="group" aria-label="Look back" className="flex gap-1.5">{([7, 14, 30] as const).map(d => <button key={d} type="button" aria-pressed={s.lookback === d}
          onClick={() => setS({ ...s, lookback: d })} className={cn('min-h-10 rounded-md border px-3.5 text-sm', s.lookback === d ? 'border-fjord bg-fjord-soft font-semibold' : 'bg-card')}>{d} days</button>)}</div>
      </div>
    </Box>
  </>
}

function CalendarSetup({ setSave }: { setSave: (f: () => () => Promise<void>) => void }) {
  const [s, setS] = useSources()
  useEffect(() => { if (s) setSave(() => async () => { await post('setup_sources_save', { calendars: s.calendars }) }) }, [s])   // eslint-disable-line react-hooks/exhaustive-deps
  return <>
    <Box title="Calendars" data-setup-calendars="">
      {!s ? <p className="text-ink-3 text-sm">Looking for your calendars…</p> : s.calendars.length ? <ul className="divide-y">{s.calendars.map((c, i) => <li key={c.name} className="flex min-h-11 flex-wrap items-center gap-3 py-2">
        <span className="min-w-56 flex-1">{c.name}</span>
        <NativeSelect value={c.kind} aria-label={'Calendar ' + c.name} className="h-10 w-auto"
          onChange={e => setS({ ...s, calendars: s.calendars.map((x, j) => j === i ? { ...x, kind: e.target.value as 'work' | 'private' | 'ignore' } : x) })}>
          <option value="work">Work</option><option value="private">Private</option><option value="ignore">Ignore</option></NativeSelect></li>)}</ul>
        : <p className="text-ink-3 text-sm">No calendars found on this Mac yet.</p>}
    </Box>
    <Box title="Online meetings"><MeetingServicesCard /></Box>
    <p className="text-ink-3 text-[13px]">Meeting recordings are transcribed on this Mac (whisper.cpp). Settings → System says if it is missing.</p>
  </>
}

function TripsSetup({ setSave }: { setSave: (f: () => () => Promise<void>) => void }) {
  const [months, setMonths] = useState(6)
  useEffect(() => { setSave(() => async () => {
    const d = new Date(); d.setMonth(d.getMonth() - months)
    await post('trip_scan', { since: d.toISOString().slice(0, 10) }).catch(() => {})
  }) }, [months])   // eslint-disable-line react-hooks/exhaustive-deps
  return <Box title="Look for trips">
    <div className="flex flex-wrap items-center gap-3"><span className="flex-1">Look for bookings in your mail since</span>
      <NativeSelect value={months} onChange={e => setMonths(Number(e.target.value))} className="h-10 w-auto" aria-label="Since">
        {[3, 6, 12, 18].map(m => <option key={m} value={m}>{m} months back</option>)}</NativeSelect></div>
    <p className="text-ink-3 text-[13px]">The scan reads booking mails in the accounts Axella reads; trips it finds show up on the Trips page to confirm.</p>
  </Box>
}

function BriefsSetup({ setSave }: { setSave: (f: () => () => Promise<void>) => void }) {
  const [topics, setTopics] = useState([{ name: '', prompt: '', days: [0] as number[] }])
  useEffect(() => { setSave(() => async () => {
    for (const t of topics.filter(t => t.name.trim() && t.prompt.trim())) await post('briefing_save', { name: t.name, prompt: t.prompt, days: t.days, time: '07:30', kind: 'research' })
  }) }, [topics])   // eslint-disable-line react-hooks/exhaustive-deps
  const upd = (i: number, p: Partial<typeof topics[0]>) => setTopics(topics.map((t, j) => j === i ? { ...t, ...p } : t))
  return <Box title="Topics to follow">
    {topics.map((t, i) => <div key={i} className="grid gap-2 border-t pt-3 first:border-0 first:pt-0 sm:grid-cols-[1fr_2fr_auto]">
      <Input value={t.name} onChange={e => upd(i, { name: e.target.value })} placeholder="e.g. Sports technology" aria-label="Topic" className="h-10" />
      <Input value={t.prompt} onChange={e => upd(i, { prompt: e.target.value })} placeholder="Why, and what to look for – e.g. timing and tracking news" aria-label="What to look for" className="h-10" />
      <NativeSelect value={t.days.length > 1 ? 'weekdays' : 'weekly'} onChange={e => upd(i, { days: e.target.value === 'weekdays' ? [0, 1, 2, 3, 4] : [0] })} className="h-10 w-auto" aria-label="How often">
        <option value="weekly">Weekly (Mon)</option><option value="weekdays">Weekdays</option></NativeSelect>
    </div>)}
    {topics.length < 3 && <Button size="sm" variant="ghost" onClick={() => setTopics([...topics, { name: '', prompt: '', days: [0] }])}><Plus />Another topic</Button>}
    <p className="text-ink-3 text-[13px]">Only the topic goes into the web searches – nothing of yours. The knowledge base fills itself from what Axella reads; nothing to set up.</p>
  </Box>
}

/* ---------- 4 Summary ---------- */
function Summary({ v, chosen, skipped, newInstall }: { v: FeaturesView; chosen: CardId[]; skipped: CardId[]; newInstall: boolean }) {
  const { go } = useApp()
  const [src, setSrc] = useState<Sources | null>(null)
  const name = v.about?.name?.split(' ')[0]
  useEffect(() => {
    post('setup_save', { done: true }).then(featuresChanged, () => {})
    get<Sources>('setup_sources').then(setSrc, () => {})
    if (newInstall) post('sweep_request', {}).catch(() => {})        // the first digest: reading the chosen look-back now
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps
  const cards = v.cards.filter(c => chosen.includes(c.id))
  const notChosen = v.cards.filter(c => !chosen.includes(c.id))
  const reads = src?.accounts.filter(a => a.read) || []
  const line = (c: CardInfo): string => {
    if (skipped.includes(c.id)) return 'Not set up yet – Settings → What Axella handles → Set up.'
    if (c.id === 'messages') return src ? `${reads.length} mail account${reads.length === 1 ? '' : 's'} (${reads.filter(a => a.kind === 'work').length} work, ${reads.filter(a => a.kind === 'private').length} private)` +
      [src.channels.imessage && 'iMessage', src.channels.whatsapp && 'WhatsApp', src.channels.signal && 'Signal'].filter(Boolean).map(x => ', ' + x).join('') +
      (newInstall ? `. Reading the last ${src.lookback} days now – about 10 minutes.` : '.') : '…'
    if (c.id === 'calendar') return src ? `${src.calendars.filter(x => x.kind !== 'ignore').length} calendars.` : '…'
    if (c.id === 'projects') return 'Axella will suggest projects from your mail on Today – you confirm them.'
    if (c.id === 'trips') return 'Looking for bookings in your mail – trips show up on the Trips page to confirm.'
    return c.includes
  }
  const leaves: string[] = []
  if (chosen.includes('messages')) leaves.push('Claude reads the mail and messages you chose, to sort and summarise them. Private contacts are never sent.')
  if (chosen.includes('briefs')) leaves.push('Topic briefs search the web for the topics you picked – only the topic.')
  if (chosen.includes('calendar')) leaves.push('Your meeting service gets the invites you send.')
  if (chosen.includes('voice')) leaves.push('The spoken digest is read aloud on your own device.')
  return <div className="mx-auto max-w-[860px] space-y-5" data-setup-summary="">
    <H title={`You're set${name ? ', ' + name : ''}.`} sub={newInstall && src ? `Axella is reading the last ${src.lookback} days now. Your first morning digest arrives at ${v.about?.digest_time || '07:30'}.`
      : 'Your choices are saved. Change any of them in Settings → What Axella handles.'} />
    <Box title="Axella handles">
      {cards.length ? cards.map(c => <div key={c.id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-t py-2.5 first:border-0" data-summary-card={c.id}>
        <span className="flex w-60 items-center gap-2.5 font-semibold"><Diamond color={c.color} size={9} />{c.title}</span>
        <span className="text-ink-2 min-w-72 flex-1 text-sm">{line(c)}</span></div>) : <p className="text-ink-2 text-sm">Only what is always included.</p>}
    </Box>
    <div className="grid gap-4 md:grid-cols-2">
      <Box title="Not now – add any time"><p className="text-ink-2 text-sm leading-relaxed">{notChosen.map(c => c.title).join(' · ') || 'Nothing – you chose everything.'}</p>
        <span className="text-ink-3 text-[13px]">Settings → What Axella handles</span></Box>
      <Box title="What leaves your home"><ul className="text-ink-2 list-disc space-y-1 pl-5 text-sm">{leaves.map(l => <li key={l}>{l}</li>)}{!leaves.length && <li>Nothing beyond the digest runs.</li>}</ul>
        <span className="text-ink-3 block text-[13px]">Claude use with these choices: {claudeWord(cards)}.</span></Box>
    </div>
    <div className="flex flex-wrap justify-end gap-3">
      <Button variant="outline" onClick={() => go({ kind: 'today' })} data-setup-today="">Go to Today</Button>
      <Button onClick={() => { go({ kind: 'today' }); setTimeout(() => openTour('welcome'), 600) }}><Check />Show me around</Button>
    </div>
  </div>
}

function claudeWord(cards: CardInfo[]) {
  const rank = { 'none yet': 0, light: 1, moderate: 2, more: 3 } as Record<string, number>
  const top = Math.max(0, ...cards.map(c => rank[c.claude] ?? 1)) + (cards.length > 4 ? 1 : 0)
  return top <= 1 ? 'light, about the same as a few chats a day' : top === 2 ? 'moderate' : 'more – several runs a day'
}
