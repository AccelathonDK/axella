/* When the calendar changes from Axella (an event added, moved or deleted, an invite accepted) every calendar view on
   the page reads Calendar again – fresh from the Mac mini, not its one-minute cache. Views also look again when the
   app comes back to the foreground and every 5 minutes while they are open. */
import { useEffect, useRef } from 'react'

const EVT = 'ax-calendar-changed'
export const calendarChanged = () => window.dispatchEvent(new CustomEvent(EVT))

/** reload(fresh): fresh=true after a change Axella made (skip the Mac mini's cache) */
export function useCalendarRefresh(reload: (fresh: boolean) => void, everyMs = 5 * 60e3) {
  const r = useRef(reload); r.current = reload
  useEffect(() => {
    const changed = () => r.current(true)
    const back = () => { if (document.visibilityState === 'visible') r.current(false) }
    window.addEventListener(EVT, changed)
    document.addEventListener('visibilitychange', back)
    const t = setInterval(() => { if (document.visibilityState === 'visible') r.current(false) }, everyMs)
    return () => { window.removeEventListener(EVT, changed); document.removeEventListener('visibilitychange', back); clearInterval(t) }
  }, [everyMs])
}
