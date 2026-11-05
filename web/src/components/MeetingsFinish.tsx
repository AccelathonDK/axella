/* Meeting prep v2, finish (setup/meetings.py): a recording uploaded in chunks as it is made (a lost connection loses
   nothing: the chunks wait and are sent again; a recording cut off is kept on the prep – Finish or Drop), the screen
   kept awake while recording, the transcription status with its setup steps, Rename speakers, Add from project…, and
   a decision or task ticking the point it answers. Owner only, like all of meeting prep. */
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { Check, ClipboardCopy, FolderKanban, X } from '@/components/ax-icons'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { NativeSelect } from '@/components/ui/input'
import { post } from '@/lib/api'
import { useApp } from '@/lib/app'
import { profile } from '@/lib/profile'
import type { Prep } from '@/lib/meetings'

export interface Rec { id: string; bytes: number; started: string; updated?: string; type: string; next: number }
type Caps = { transcribe: boolean; why?: string | null; model?: string | null; language?: string | null }

const rid = () => 'r' + Array.from(crypto.getRandomValues(new Uint8Array(6)), b => b.toString(16).padStart(2, '0')).join('')
const mb = (n: number) => n < 1e6 ? Math.max(1, Math.round(n / 1e3)) + ' kB' : (n / 1e6).toFixed(1) + ' MB'

async function sendChunk(prepId: string, rec: string, seq: number, blob: Blob) {
  const r = await fetch(`api/meeting_record_chunk?id=${encodeURIComponent(prepId)}&rec=${rec}&seq=${seq}`, {
    method: 'POST', headers: { 'X-Axella': '1', 'Content-Type': blob.type.split(';')[0] || 'audio/webm' }, body: blob })
  const j = await r.json().catch(() => ({ ok: false, error: 'HTTP ' + r.status }))
  if (!j.ok) throw new Error(j.error || 'not sent')
  return j.result as { next: number }
}

/** Record with chunks uploaded as they're made (every 5 s). Chunks that couldn't be sent wait in memory and go as soon
    as the Mac mini answers again; the screen is kept awake (Wake Lock) while recording. */
export function useChunkRecorder(prepId: string, onDone: (r: { id: string; status: string; error?: string | null }) => void) {
  const [state, setState] = useState<{ t0: number; rec: string; pending: number; sent: number } | null>(null)
  const ref = useRef<{ mr: MediaRecorder; rec: string; queue: Blob[]; seq: number; busy: boolean; stopping: boolean; lock: any; type: string } | null>(null)
  const pump = async () => {
    const c = ref.current
    if (!c || c.busy) return
    c.busy = true
    try {
      while (c.queue.length) {
        try { await sendChunk(prepId, c.rec, c.seq, c.queue[0]); c.queue.shift(); c.seq++ }
        catch (e: any) {
          const m = /missing chunk (\d+)/.exec(e.message || '')
          if (m && +m[1] < c.seq) { c.seq = +m[1]; continue }     // the Mac mini has fewer: never happens with this queue, but safe
          break                                                  // offline or slow: kept, sent on the next round
        }
      }
    } finally { c.busy = false; setState(s => s && { ...s, pending: c.queue.length, sent: c.seq }) }
    if (c.stopping && !c.queue.length) {
      ref.current = null
      try { c.lock?.release?.() } catch { /* */ }
      const d = new Date()
      try {
        const r = await post<{ result: { id: string; status: string; error?: string | null } }>('meeting_record_finish',
          { id: prepId, rec: c.rec, name: `Recording ${d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}${c.type.includes('mp4') ? '.m4a' : '.webm'}` })
        onDone(r.result)
      } catch (e: any) { toast.error('The recording is kept on the prep – Finish it there: ' + e.message) }
      setState(null)
    }
  }
  useEffect(() => { if (!state) return; const t = setInterval(pump, 4000); return () => clearInterval(t) })   // retry while there is a queue
  useEffect(() => {
    const vis = () => { if (document.visibilityState === 'hidden' && ref.current && !ref.current.stopping) toast.warning('Recording – keep Axella open, or the phone may stop it') }
    document.addEventListener('visibilitychange', vis); return () => document.removeEventListener('visibilitychange', vis)
  }, [])
  async function start() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const type = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm'].find(t => (window as any).MediaRecorder?.isTypeSupported?.(t)) || ''
      const mr = new MediaRecorder(stream, type ? { mimeType: type } : undefined)
      let lock: any = null
      try { lock = await (navigator as any).wakeLock?.request('screen') } catch { /* not offered: the hint says keep the screen on */ }
      const c = { mr, rec: rid(), queue: [] as Blob[], seq: 0, busy: false, stopping: false, lock, type: mr.mimeType || type || 'audio/webm' }
      ref.current = c
      mr.ondataavailable = e => { if (e.data.size) { c.queue.push(e.data); pump() } }
      mr.onstop = () => { mr.stream.getTracks().forEach(t => t.stop()); c.stopping = true; pump() }
      mr.start(5000)
      setState({ t0: Date.now(), rec: c.rec, pending: 0, sent: 0 })
    } catch (e: any) { toast.error('Could not start recording: ' + (e.message || 'no microphone')) }
  }
  function stop() { const c = ref.current; if (c && c.mr.state !== 'inactive') c.mr.stop() }
  return { state, start, stop }
}

/** Recordings cut off (a lost connection, the phone locked): what arrived is kept – Finish (transcribe it) or Drop. */
export function WaitingRecordings({ prep, current, onChanged }: { prep: Prep & { recordings?: Record<string, Rec> }; current?: string; onChanged: () => void }) {
  const list = Object.values(prep.recordings || {}).filter(r => r.id !== current)
  if (!list.length) return null
  const act = async (a: string, r: Rec, ok: string) => { try { await post(a, { id: prep.id, rec: r.id, title: prep.title, name: 'Recording ' + new Date(r.started).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) }); toast(ok); onChanged() } catch (e: any) { toast.error(e.message) } }
  return <div className="space-y-1.5" data-rec-waiting="">{list.map(r => <div key={r.id} className="bg-dawn/10 flex flex-wrap items-center gap-2 rounded-md px-3 py-2 text-[13px]">
    <span className="min-w-0 flex-1">A recording from {new Date(r.started).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })} was cut off – {mb(r.bytes)} arrived and is kept.</span>
    <Button size="pill" onClick={() => act('meeting_record_finish', r, 'Finished – transcribing on the Mac mini')}><Check />Finish</Button>
    <Button size="pill" variant="ghost" onClick={() => act('meeting_record_drop', r, 'Dropped')}><X />Drop</Button>
  </div>)}<p className="text-ink-3 text-[11.5px]">To go on recording, tap Record again – it becomes a second recording of the same meeting.</p></div>
}

/** Transcription: set up or not, and how to set it up (copyable). */
export function TranscribeStatus({ caps }: { caps: Caps | null }) {
  if (!caps) return null
  if (caps.transcribe) return <p className="text-ink-3 text-[11.5px]" data-transcribe-status="ok">Recordings are transcribed on this Mac mini (whisper{caps.model ? ', ' + caps.model.replace(/^ggml-|\.bin$/g, '') : ''}{caps.language && caps.language !== 'auto' ? ', ' + caps.language : ''}).</p>
  const steps = 'cd ~/dev/own/home-server/axella\ntools/setup-whisper.sh\nlaunchctl kickstart -k gui/$(id -u)/dk.mortentoft.axella-actions'
  return <div className="text-ink-3 space-y-1 text-[11.5px]" data-transcribe-status="off">
    <p>Not set up: recordings are kept, and you can paste or upload a transcript. {caps.why}</p>
    <p>To set it up, in Terminal on the Mac mini:</p>
    <pre className="bg-bg-2/60 overflow-x-auto rounded px-2 py-1.5 font-mono text-[11.5px]">{steps}</pre>
    <Button size="pill" variant="ghost" onClick={() => navigator.clipboard.writeText(steps).then(() => toast('Copied'), () => {})}><ClipboardCopy />Copy</Button>
  </div>
}

/** Rename speakers: each label of the transcript → one of the meeting's people (or you). The stored text keeps its labels. */
export function Speakers({ prep, materialId, labels, names, onChanged }: { prep: Prep; materialId: string; labels: string[]; names?: Record<string, string>; onChanged: () => void }) {
  const [v, setV] = useState<Record<string, string>>(names || {})
  if (!labels.length) return null
  const people = [...new Set([profile().owner.name || profile().owner.first_name, ...prep.attendees.map(a => a.name)].filter(Boolean))]
  async function save() { try { await post('meeting_speakers', { id: prep.id, material: materialId, names: v, title: prep.title }); toast('Speakers named – Find outcomes uses the names'); onChanged() } catch (e: any) { toast.error(e.message) } }
  return <div className="mt-2 space-y-1.5" data-speakers="">
    <div className="ax-label">Speakers</div>
    {labels.map(l => <label key={l} className="flex items-center gap-2 text-[13px]"><span className="text-ink-3 w-28 shrink-0 truncate font-mono text-[12px]">{l}</span>
      <NativeSelect className="w-auto" value={v[l] || ''} onChange={e => setV({ ...v, [l]: e.target.value })} aria-label={'Name for ' + l}>
        <option value="">—</option>{people.map(p => <option key={p} value={p}>{p}</option>)}</NativeSelect></label>)}
    <Button size="pill" variant="outline" onClick={save}><Check />Save names</Button>
  </div>
}

/** Add from project…: the linked project's notes, links and documents – by reference (the project keeps the original). */
export function ProjectAdd({ prep, onChanged }: { prep: Prep; onChanged: () => void }) {
  const { ax } = useApp()
  const [open, setOpen] = useState(false)
  const pr = ax.projects.find(p => p.id === prep.project)
  if (!pr) return null
  const have = new Set(prep.materials.filter(m => (m as any).kind === 'project').map(m => (m as any).ref))
  const rows: [string, string, string][] = [...(pr.notes || []).map(n => ['note', n.id, n.text.split('\n')[0].slice(0, 80)] as [string, string, string]),
    ...(pr.links || []).map(l => ['link', l.id, l.title || l.url] as [string, string, string]), ...(pr.files || []).map(f => ['file', f.id, f.name] as [string, string, string])]
  async function add(kind: string, ref: string, name: string) {
    try { await post('meeting_project_add', { id: prep.id, project: pr!.id, kind, ref, name, title: prep.title }); toast('Added from ' + pr!.name); onChanged() } catch (e: any) { toast.error(e.message) }
  }
  return <>
    <Button size="pill" variant="outline" onClick={() => setOpen(true)} data-project-add=""><FolderKanban />Add from project…</Button>
    {open && <Dialog open onOpenChange={o => !o && setOpen(false)}><DialogContent className="sm:max-w-md">
      <div className="space-y-2 p-5"><DialogTitle className="text-lg font-semibold">From {pr.name}</DialogTitle>
        {!rows.length && <p className="text-ink-3 text-sm">The project has no notes, links or documents yet.</p>}
        <ul className="max-h-80 space-y-1 overflow-y-auto">{rows.map(([k, id, name]) => <li key={id} className="flex items-center gap-2 text-sm">
          <span className="text-ink-3 w-12 shrink-0 text-[12px]">{k === 'note' ? 'Note' : k === 'link' ? 'Link' : 'File'}</span><span className="min-w-0 flex-1 truncate">{name}</span>
          {have.has(id) ? <span className="text-ink-3 text-[12px]">added</span> : <Button size="pill" variant="outline" onClick={() => add(k, id, name)}>Add</Button>}</li>)}</ul>
        <p className="text-ink-3 text-[11.5px]">Added by reference: the project keeps the original, and the prep reads its newest version.</p>
        <div className="flex justify-end"><Button size="pill" variant="ghost" onClick={() => setOpen(false)}>Done</Button></div></div>
    </DialogContent></Dialog>}
  </>
}

/** A decision or task → the point it answers (ticked, with its outcome). */
export function AnswersPoint({ prep, outcomeId, onChanged }: { prep: Prep; outcomeId?: string; onChanged: () => void }) {
  const pts = prep.points.filter(p => p.id)
  if (!outcomeId || !pts.length) return null
  const cur = pts.find(p => (p as any).outcome?.id === outcomeId)
  return <NativeSelect className="h-8 w-auto max-w-44 text-[12.5px]" aria-label="Answers point" value={cur?.id || ''} data-answers-point=""
    onChange={async e => { const pid = e.target.value || cur?.id; if (!pid) return
      try { await post('meeting_point_outcome', { id: prep.id, point: pid, outcome: e.target.value ? outcomeId : null, title: prep.title }); toast(e.target.value ? 'Point ticked with its outcome' : 'Point open again'); onChanged() } catch (x: any) { toast.error(x.message) } }}>
    <option value="">Answers a point…</option>{pts.map(p => <option key={p.id} value={p.id}>{p.text.slice(0, 50)}</option>)}</NativeSelect>
}
