# Axella dashboard (React + shadcn/ui)

Source of the dashboard served at /axella/. Vite + React 19 + TypeScript + Tailwind v4, shadcn-style components on Radix.

    npm install
    npm run deploy     # build -> dist/, then copy into the parent folder that is served at /axella/

Nothing is sent automatically. Mail replies and new mail are written in the dashboard and sent by the Mac mini's Mail only when you tap Send, confirm, and let the 6-second undo run out – or saved as a draft in Mail instead. WhatsApp and Messages replies open the app with the draft.
