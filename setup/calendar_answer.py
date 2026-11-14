"""Answer a meeting invitation in Calendar itself – Accept / Maybe / Decline on its row under Calendar's invitations
(the toolbar's inbox button, tab "New"). On Exchange and iCloud only that answer reaches the owner's own mailbox: the
invitation leaves "New", and the account's server sends the organizer the reply. Axella's own reply mail would not.

How: macOS Accessibility (System Events), the way a screen reader presses a button – no mouse, no screen
coordinates. Calendar's elements are found by their fixed internal identifiers (CALMainWindow, inbox-button,
inbox-switcher-control, accept-button, maybe-button, decline-button), so the Mac's language doesn't matter. Only the
invitations panel is touched, and only one of the three answer buttons is pressed.

The meeting's title, organizer and time reach the script only as argv – never pasted into the script text.

Results (one word, so the caller can decide; nothing else is ever sent from here):
  answered        pressed, and the row left "New" – done
  not_found       no matching row under New (and none under Replied) – this invitation isn't in Calendar
  replied         no row under New, but one under Replied – already answered in Calendar
  ambiguous       more than one row matches – nothing pressed
  unconfirmed     pressed, but the row didn't leave "New" within the wait – check Calendar
  no_access       the action service has no Accessibility permission
  no_calendar / no_window / no_inbox / no_button   Calendar or its panel couldn't be reached – nothing pressed
Python 3.9."""

BUTTON = {'accepted': 'accept-button', 'tentative': 'maybe-button', 'declined': 'decline-button'}
OK = 'answered'
NOT_IN_CALENDAR = 'not_found'
REASONS = {
    'replied': 'it is already answered in Calendar',
    'ambiguous': 'more than one invitation in Calendar matches',
    'unconfirmed': "Calendar didn't confirm the answer",
    'no_access': "Axella has no Accessibility permission on the Mac mini (System Settings → Privacy & Security → Accessibility)",
    'no_calendar': "Calendar didn't start",
    'no_window': "Calendar's window couldn't be opened",
    'no_inbox': "Calendar's invitations panel couldn't be found",
    'no_button': "the answer button couldn't be found",
}

SCRIPT = r'''
on idOf(e)
  tell application "System Events"
    try
      return (value of attribute "AXIdentifier" of e) as text
    on error
      return ""
    end try
  end tell
end idOf

on rowsOf(w)
  tell application "System Events"
    try
      return rows of table 1 of scroll area 1 of scroll area 1 of splitter group 1 of splitter group 1 of w
    on error
      return {}
    end try
  end tell
end rowsOf

on textsOf(r)
  tell application "System Events"
    try
      return value of every static text of UI element 1 of r
    on error
      return {}
    end try
  end tell
end textsOf

on matches(w, wantTitle, wantOrg, wantTime1, wantTime2)
  set hits to {}
  repeat with r in my rowsOf(w)
    set t to my textsOf(r)
    if (count of t) > 0 then
      if ((item 1 of t) as text) is wantTitle then set end of hits to {r, t}
    end if
  end repeat
  if (count of hits) > 1 and wantOrg is not "" then
    set narrowed to {}
    repeat with h in hits
      set t to item 2 of h
      if (count of t) > 1 then
        if ((item 2 of t) as text) contains wantOrg then set end of narrowed to h
      end if
    end repeat
    if (count of narrowed) > 0 then set hits to narrowed
  end if
  if (count of hits) > 1 then
    set narrowed to {}
    repeat with h in hits
      set t to item 2 of h
      if (count of t) > 2 then
        set s to (item 3 of t) as text
        if s contains wantTime1 or s contains wantTime2 then set end of narrowed to h
      end if
    end repeat
    if (count of narrowed) > 0 then set hits to narrowed
  end if
  return hits
end matches

on pickTab(w, tabId)
  tell application "System Events"
    try
      set tg to missing value
      repeat with x in tab groups of scroll area 1 of splitter group 1 of splitter group 1 of w
        if my idOf(x) is "inbox-switcher-control" then set tg to x
      end repeat
      if tg is missing value then return false
      repeat with rb in radio buttons of tg
        if my idOf(rb) is tabId then
          perform action "AXPress" of rb
          delay 0.8
          return true
        end if
      end repeat
    end try
  end tell
  return false
end pickTab

on run argv
  set wantTitle to item 1 of argv
  set wantOrg to item 2 of argv
  set wantTime1 to item 3 of argv
  set wantTime2 to item 4 of argv
  set wantButton to item 5 of argv
  tell application "System Events"
    if not (UI elements enabled) then return "no_access"
  end tell
  set wasRunning to (application "Calendar" is running)
  tell application "Calendar" to launch
  tell application "System Events"
    set t0 to current date
    repeat until (exists process "Calendar")
      if ((current date) - t0) > 20 then return "no_calendar"
      delay 0.5
    end repeat
    tell process "Calendar"
      if (count of windows) = 0 then
        tell application "Calendar" to reopen
        delay 2
        if not wasRunning then set visible to false
      end if
      set w to missing value
      repeat with x in windows
        if my idOf(x) is "CALMainWindow" then set w to x
      end repeat
      if w is missing value then return "no_window"
      set inboxBtn to missing value
      set calBtn to missing value
      repeat with g in groups of toolbar 1 of w
        try
          repeat with rb in radio buttons of radio group 1 of g
            if my idOf(rb) is "inbox-button" then set inboxBtn to rb
            if my idOf(rb) is "calendars-button" then set calBtn to rb
          end repeat
        end try
      end repeat
      if inboxBtn is missing value then return "no_inbox"
      set opened to false
      if (value of inboxBtn as text) is not "1" then
        perform action "AXPress" of inboxBtn
        set opened to true
        delay 1
      end if
    end tell
  end tell
  set outcome to "no_inbox"
  if my pickTab(w, "inbox-button") then
    set hits to my matches(w, wantTitle, wantOrg, wantTime1, wantTime2)
    if wantButton is "" then
      set outcome to "found:" & ((count of hits) as text) & "/" & ((count of my rowsOf(w)) as text)
    else if (count of hits) = 0 then
      set outcome to "not_found"
      if my pickTab(w, "replied-button") then
        if (count of my matches(w, wantTitle, wantOrg, wantTime1, wantTime2)) > 0 then set outcome to "replied"
        my pickTab(w, "inbox-button")
      end if
    else if (count of hits) > 1 then
      set outcome to "ambiguous"
    else
      set r to item 1 of item 1 of hits
      set btn to missing value
      tell application "System Events"
        try
          repeat with b in buttons of UI element 1 of r
            if my idOf(b) is wantButton then set btn to b
          end repeat
        end try
        if btn is missing value then
          set outcome to "no_button"
        else
          perform action "AXPress" of btn
          set outcome to "unconfirmed"
        end if
      end tell
      if outcome is "unconfirmed" then
        repeat 30 times
          delay 0.5
          if (count of my matches(w, wantTitle, wantOrg, wantTime1, wantTime2)) = 0 then
            set outcome to "answered"
            exit repeat
          end if
        end repeat
      end if
    end if
  end if
  if opened and calBtn is not missing value then
    tell application "System Events" to perform action "AXPress" of calBtn
  end if
  return outcome
end run
'''


def times(start_iso):
    """The meeting's local start as Calendar writes it in a row ("16.00" or "16:00") – a tie-breaker only."""
    import datetime
    try:
        d = datetime.datetime.fromisoformat(str(start_iso).replace('Z', '+00:00'))
        d = d.astimezone() if d.tzinfo else d
        return d.strftime('%H.%M'), d.strftime('%H:%M')
    except (TypeError, ValueError):
        return '\u0000', '\u0000'           # matches nothing


def look(osa, title, organizer='', start_iso='', timeout=90):
    """The live check: find the invitation under New without pressing anything. → "found:<matches>/<rows>" or a reason."""
    t1, t2 = times(start_iso)
    return str(osa(SCRIPT, str(title or '').strip()[:300], str(organizer or '').strip()[:120], t1, t2, '', timeout=timeout) or '').strip()


def answer(osa, title, organizer, start_iso, response, timeout=90):
    """Press the answer in Calendar. osa(script, *argv, timeout=) runs AppleScript (argv only). → one result word."""
    if response not in BUTTON:
        raise ValueError('accepted, tentative or declined')
    t1, t2 = times(start_iso)
    out = osa(SCRIPT, str(title or '').strip()[:300], str(organizer or '').strip()[:120], t1, t2, BUTTON[response], timeout=timeout)
    out = str(out or '').strip()
    return out if out in REASONS or out in (OK, NOT_IN_CALENDAR) else 'no_inbox'
