import { Marked } from 'marked'
const esc = (s: string) => s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!))
const unesc = (s: string) => esc(s).replace(/&amp;/g, '&').replace(/&#39;/g, "'").replace(/&quot;/g, '"')
const safeHref = (h: string) => h.replace(/href="(?!https?:\/\/|mailto:|tel:|sms:|message:)[^"]*"/gi, 'href="#"')
// Images are never rendered: a remote <img> would load as soon as a card is shown (tracking, IP leak). The alt text stays.
const withLinks = new Marked({ renderer: { image: (_href: string, _title: string | null, text: string) => text } })
// For caller-influenced text (call summaries): no links either – just their text.
const noLinks = new Marked({ renderer: {
  image: (_href: string, _title: string | null, text: string) => text,
  link: (_href: string, _title: string | null | undefined, text: string) => text,
} })
/** inline markdown on escaped text (no raw HTML from digests, no images); `links: false` also drops links */
export const mdInline = (s?: string, o: { links?: boolean } = {}) =>
  safeHref((o.links === false ? noLinks : withLinks).parseInline(unesc(s ?? '')) as string)
