import type { SVGProps } from 'react'
/* lucide has no brand icon for WhatsApp – a simple chat bubble with a handset */
export function WhatsApp(p: SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" {...p}>
    <path d="M3.5 20.5l1.3-4A8.5 8.5 0 1 1 8 19.4z" /><path d="M9 9.5c0 3 2.5 5.5 5.5 5.5l1-1.3-1.7-1-1 .8a4 4 0 0 1-2.3-2.3l.8-1-1-1.7z" /></svg>
}
/* The rune (design system "Axella"): an A and an X in one stroke – a diamond apex whose lower sides cross into the X.
   On its tile it flips with the theme (graphite on light grounds, light on dark), so it always reads as a solid object.
   Stroke steps up as it gets smaller so it holds at 16–24px. Never rounded, outlined, rotated or recoloured. */
export const RUNE = 'M30 76L68 38L50 20L32 38L70 76'
export function Rune({ size = 24, className = '' }: { size?: number; className?: string }) {
  const w = size <= 24 ? 11 : size <= 48 ? 9 : 8
  return <svg viewBox="0 0 100 100" width={size} height={size} className={className} aria-hidden>
    <path d={RUNE} fill="none" stroke="currentColor" strokeWidth={w} strokeLinejoin="miter" strokeMiterlimit={10} /></svg>
}
export function Brand({ size = 28, className = '' }: { size?: number; className?: string }) {
  return <span role="img" aria-label="Axella" className={'bg-surface-inverse text-on-inverse inline-grid shrink-0 place-items-center rounded-[22%] ' + className}
    style={{ width: size, height: size }}><Rune size={Math.round(size * 0.74)} /></span>
}
