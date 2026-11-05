/* What an item row can do (done, snooze, file …), so iPhone swipes reach the same actions as the buttons. */
export interface RowApi {
  done?: () => void; undo?: () => void; snooze?: () => void; task?: () => void
  file?: () => void; fileLabel?: string; pick?: () => void; trash?: () => void
  reply?: () => void; preview?: () => void
}
