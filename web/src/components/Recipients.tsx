/* To / Cc / Bcc for the mail composer, Apple Mail style: each person is a chip, typing suggests people you mail
   (GET compose_contacts), Enter / comma / Tab turns a typed address into a chip, Backspace on an empty field removes
   the last one. Only plain addresses leave here – the Mac mini checks them again (setup/axella-actions.py recipients). */
import { useEffect, useMemo, useRef, useState } from 'react'
import { X } from '@/components/ax-icons'
import { get } from '@/lib/api'
import { cn } from '@/lib/utils'

export interface Person { name?: string; address: string }
const MAIL_RE = /^[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$/
export const validAddress = (a: string) => MAIL_RE.test(a.trim())

let contacts: Person[] | null = null
let loading: Promise<Person[]> | null = null
function loadContacts() {
  if (contacts) return Promise.resolve(contacts)
  loading ||= get<{ contacts: { address: string; name?: string }[] }>('compose_contacts')
    .then(j => (contacts = (j.contacts || []).map(c => ({ address: c.address, name: c.name || undefined }))))
    .catch(() => (contacts = []))
  return loading
}

export function RecipientField({ label, value, onChange, autoFocus, right }: {
  label: string; value: Person[]; onChange: (v: Person[]) => void; autoFocus?: boolean; right?: React.ReactNode
}) {
  const [q, setQ] = useState('')
  const [all, setAll] = useState<Person[]>(contacts || [])
  const [hi, setHi] = useState(0)
  const [focus, setFocus] = useState(false)
  const [err, setErr] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => { loadContacts().then(setAll) }, [])
  const taken = new Set(value.map(v => v.address.toLowerCase()))
  const hits = useMemo(() => {
    const t = q.trim().toLowerCase()
    if (t.length < 2) return []
    return all.filter(c => !taken.has(c.address.toLowerCase()) && (c.address.includes(t) || (c.name || '').toLowerCase().includes(t))).slice(0, 6)
  }, [q, all, value])   // eslint-disable-line react-hooks/exhaustive-deps

  function add(p: Person) {
    if (taken.has(p.address.toLowerCase())) { setQ(''); return }
    onChange([...value, { address: p.address.trim(), name: p.name }]); setQ(''); setHi(0); setErr(false)
  }
  function commit() {
    const t = q.trim().replace(/[,;]+$/, '')
    if (!t) return true
    if (hits[hi] && !validAddress(t)) { add(hits[hi]); return true }
    // "Name <address>" pasted from somewhere: keep the address
    const m = t.match(/<([^<>\s]+@[^<>\s]+)>/), addr = m ? m[1] : t
    if (validAddress(addr)) { add({ address: addr, name: m ? t.slice(0, t.indexOf('<')).replace(/["']/g, '').trim() || undefined : undefined }); return true }
    setErr(true); return false
  }
  return <div className="relative flex items-start gap-2 border-b px-4 py-1.5 text-[13px]" onClick={() => input.current?.focus()}>
    <span className="text-ink-3 w-9 shrink-0 pt-1.5">{label}</span>
    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
      {value.map(p => <span key={p.address} title={p.address} data-rcpt={p.address}
        className="bg-fjord-soft text-fjord inline-flex max-w-full items-center gap-1 rounded-full py-0.5 pr-1 pl-2.5 text-[13px] font-medium">
        <span className="truncate">{p.name || p.address}</span>
        <button type="button" aria-label={'Remove ' + (p.name || p.address)} className="hover:bg-fjord/15 rounded-full p-0.5"
          onClick={e => { e.stopPropagation(); onChange(value.filter(x => x !== p)) }}><X className="size-3" /></button>
      </span>)}
      <input ref={input} value={q} autoFocus={autoFocus} aria-label={label} inputMode="email" autoCapitalize="off" autoCorrect="off" spellCheck={false}
        onChange={e => { const v = e.target.value; if (/[,;]\s*$/.test(v)) { setQ(v); setTimeout(commit); return } setQ(v); setHi(0); setErr(false) }}
        onFocus={() => setFocus(true)} onBlur={() => { setTimeout(() => setFocus(false), 150); commit() }}
        onPaste={e => {
          const t = e.clipboardData.getData('text'); if (!/[,;\n]/.test(t)) return
          e.preventDefault()
          const add2: Person[] = []
          t.split(/[,;\n]+/).forEach(x => { const m = x.match(/<([^<>\s]+@[^<>\s]+)>/), a = (m ? m[1] : x).trim(); if (validAddress(a) && !taken.has(a.toLowerCase()) && !add2.some(y => y.address.toLowerCase() === a.toLowerCase())) add2.push({ address: a }) })
          onChange([...value, ...add2])
        }}
        onKeyDown={e => {
          if (e.key === 'Enter' || (e.key === 'Tab' && q.trim())) { if (q.trim()) { e.preventDefault(); commit() } }
          else if (e.key === 'Backspace' && !q && value.length) onChange(value.slice(0, -1))
          else if (e.key === 'ArrowDown' && hits.length) { e.preventDefault(); setHi(h => Math.min(hits.length - 1, h + 1)) }
          else if (e.key === 'ArrowUp' && hits.length) { e.preventDefault(); setHi(h => Math.max(0, h - 1)) }
        }}
        className={cn('min-w-[8rem] flex-1 bg-transparent py-1 outline-none', err && 'text-dawn')} placeholder={value.length ? '' : 'Name or address'} />
    </div>
    {right}
    {focus && hits.length > 0 && <div className="bg-popover shadow-float absolute top-full left-12 z-20 mt-1 w-[min(22rem,calc(100%-3.5rem))] overflow-hidden rounded-md border py-1" role="listbox">
      {hits.map((h, i) => <button key={h.address} type="button" role="option" aria-selected={i === hi}
        onMouseDown={e => { e.preventDefault(); add(h) }}
        className={cn('flex w-full flex-col px-3 py-1.5 text-left', i === hi && 'bg-bg-2')}>
        <span className="text-[13px] font-medium">{h.name || h.address}</span>
        {h.name && <span className="text-ink-3 text-[12px]">{h.address}</span>}
      </button>)}
    </div>}
  </div>
}

/* "Sam", "Sam + 2 others" – the name on the Send button and in its confirm */
export function recipientLabel(to: Person[], cc: Person[], bcc: Person[]) {
  const first = to[0] ? (to[0].name || to[0].address).split(/\s+/)[0] : 'them'
  const more = to.length + cc.length + bcc.length - 1
  return more > 0 ? `${first} + ${more} other${more > 1 ? 's' : ''}` : first
}
