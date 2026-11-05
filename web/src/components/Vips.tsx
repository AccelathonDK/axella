/* Settings → VIPs: the "## VIP …" lists in contacts.md – add, edit, move between lists, remove. The Mac mini writes
   one fixed, checked line shape (setup/axella-actions.py vip_action); anything fancier stays editable in contacts.md. */
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Check, PencilLine, Plus, Star, Trash2, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Input, NativeSelect } from '@/components/ui/input'
import { SectionCard } from '@/components/Section'
import { get } from '@/lib/api'
import { useApp } from '@/lib/app'
import { loadVips } from '@/lib/vips'
import { cn } from '@/lib/utils'

interface V { name: string; list: string; detail?: string }
interface L { title: string; work: boolean }

export function VipsCard() {
  const { ax } = useApp()
  const [d, setD] = useState<{ vips: V[]; lists: L[] } | null>(null)
  const [err, setErr] = useState('')
  const [edit, setEdit] = useState<string | null>(null)
  const load = useCallback(() => get<{ vips?: V[]; lists?: L[] }>('vips').then(j => {
    setD({ vips: Array.isArray(j.vips) ? j.vips : [], lists: Array.isArray(j.lists) ? j.lists : [] }); setErr('')
  }).catch(e => setErr(e.message)), [])
  useEffect(() => { load() }, [load])

  async function act(a: string, body: object, ok: string) {
    try { await ax.act(a, body, []); toast(ok); await load(); loadVips(); return true }
    catch (e: any) { toast.error(e.message); return false }
  }
  if (err) return <div className="text-dawn rounded-lg border p-4 text-sm">Couldn't load the VIP lists: {err}</div>
  if (!d) return null
  const lists = d.lists.length ? d.lists : [{ title: 'VIP', work: false }]
  return <>
    {lists.map(l => {
      const people = d.vips.filter(v => v.list === l.title)
      return <SectionCard key={l.title} id={'vip-' + l.title} icon={Star} title={(t => t ? t[0].toUpperCase() + t.slice(1) : 'VIP')(l.title.replace(/^VIP\s*[–-]?\s*/i, ''))} count={people.length}
        sub={l.work ? 'Work – used for work mail and calls' : 'Private'}>
        <div className="divide-y">
          {!people.length && <div className="text-ink-3 px-4 py-3 text-sm">Nobody on this list yet.</div>}
          {people.map(v => edit === v.name
            ? <EditRow key={v.name} v={v} lists={lists} onCancel={() => setEdit(null)}
                onSave={async (p) => { if (await act('vip_update', { name: v.name, ...p }, 'Saved')) setEdit(null) }} />
            : <Row key={v.name} v={v} onEdit={() => setEdit(v.name)} onRemove={() => act('vip_remove', { name: v.name }, v.name + ' is no longer a VIP')} />)}
        </div>
      </SectionCard>
    })}
    <AddVip lists={lists} onAdd={(p) => act('vip_add', { ...p, strict: true }, p.name + ' added to VIPs')} />
    <p className="text-ink-3 px-1 text-[12.5px] leading-relaxed">VIPs start at "Before noon" and never go below "By end of day". A VIP only counts when the
      address or number matches – a display name alone isn't enough. Everything is stored in <code className="font-mono">contacts.md</code> on the Mac mini, which you can also edit by hand.</p>
  </>
}

function Row({ v, onEdit, onRemove }: { v: V; onEdit: () => void; onRemove: () => void }) {
  const [armed, setArmed] = useState(false)
  useEffect(() => { if (!armed) return; const t = setTimeout(() => setArmed(false), 3000); return () => clearTimeout(t) }, [armed])
  return <div className="flex min-h-12 items-center gap-3 px-4 py-2.5" data-vip={v.name}>
    <div className="min-w-0 flex-1">
      <div className="text-[15px] font-medium">{v.name}</div>
      {v.detail && <div className="text-ink-3 truncate text-[13px]">{v.detail}</div>}
    </div>
    <Button size="icon-pill" variant="ghost" aria-label={'Edit ' + v.name} onClick={onEdit}><PencilLine /></Button>
    <Button size="pill" variant={armed ? 'destructive' : 'ghost'} aria-label={armed ? 'Tap again to remove ' + v.name : 'Remove ' + v.name}
      onClick={() => armed ? onRemove() : setArmed(true)} className={cn(!armed && 'w-9 px-0')}>
      <Trash2 />{armed && 'Remove?'}</Button>
  </div>
}

function EditRow({ v, lists, onSave, onCancel }: { v: V; lists: L[]; onSave: (p: object) => void; onCancel: () => void }) {
  const [name, setName] = useState(v.name), [detail, setDetail] = useState(v.detail || ''), [list, setList] = useState(v.list)
  const [busy, setBusy] = useState(false)
  return <form className="space-y-2 bg-bg-2/40 px-4 py-3" onSubmit={async e => { e.preventDefault(); setBusy(true); await onSave({ new_name: name, detail, list }); setBusy(false) }}>
    <div className="grid gap-2 sm:grid-cols-[1fr_1.4fr]">
      <label className="text-[12.5px] font-semibold">Name<Input value={name} onChange={e => setName(e.target.value)} maxLength={60} className="mt-1" autoFocus /></label>
      <label className="text-[12.5px] font-semibold">Address, number or note<Input value={detail} onChange={e => setDetail(e.target.value)} maxLength={160} className="mt-1"
        placeholder="kim@example.com (partner)" /></label>
    </div>
    <div className="flex flex-wrap items-center gap-2">
      {lists.length > 1 && <NativeSelect value={list} onChange={e => setList(e.target.value)} aria-label="List" className="h-8 w-auto text-sm">
        {lists.map(l => <option key={l.title} value={l.title}>{l.title}</option>)}</NativeSelect>}
      <Button type="submit" size="sm" disabled={busy || !name.trim()}><Check />Save</Button>
      <Button type="button" size="sm" variant="ghost" onClick={onCancel}><X />Cancel</Button>
    </div>
  </form>
}

function AddVip({ lists, onAdd }: { lists: L[]; onAdd: (p: { name: string; address: string; note: string; list?: string }) => Promise<boolean> }) {
  const [name, setName] = useState(''), [address, setAddress] = useState(''), [note, setNote] = useState('')
  const [list, setList] = useState(lists[0]?.title || ''), [busy, setBusy] = useState(false)
  useEffect(() => { if (!lists.some(l => l.title === list)) setList(lists[0]?.title || '') }, [lists, list])
  return <SectionCard id="vip-add" icon={Plus} title="Add a VIP" sub="Name, and the address or number they write from">
    <form className="space-y-2 p-4" onSubmit={async e => {
      e.preventDefault(); if (!name.trim()) return
      setBusy(true)
      if (await onAdd({ name: name.trim(), address: address.trim(), note: note.trim(), list: lists.length > 1 || lists[0]?.title !== 'VIP' ? list : undefined })) { setName(''); setAddress(''); setNote('') }
      setBusy(false)
    }}>
      <div className="grid gap-2 sm:grid-cols-3">
        <Input value={name} onChange={e => setName(e.target.value)} placeholder="Name" aria-label="Name" maxLength={60} />
        <Input value={address} onChange={e => setAddress(e.target.value)} placeholder="E-mail or phone (recommended)" aria-label="E-mail or phone" maxLength={80} inputMode="email" />
        <Input value={note} onChange={e => setNote(e.target.value)} placeholder="Note, e.g. partner (optional)" aria-label="Note" maxLength={160} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {lists.length > 1 && <NativeSelect value={list} onChange={e => setList(e.target.value)} aria-label="List" className="h-9 w-auto text-sm">
          {lists.map(l => <option key={l.title} value={l.title}>{l.title}</option>)}</NativeSelect>}
        <Button type="submit" disabled={busy || !name.trim()}><Plus />Add VIP</Button>
      </div>
    </form>
  </SectionCard>
}
