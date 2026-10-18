import type { ReactNode } from 'react'
import { ChevronIcon } from './icons'

interface Props {
  summary: ReactNode
  children: ReactNode
  className?: string
}

/** Native <details> with a visible, rotating chevron (the default marker is hidden). */
export function Disclosure({ summary, children, className = '' }: Props) {
  return (
    <details className={`group ${className}`}>
      <summary className="inline-flex min-h-8 cursor-pointer list-none items-center gap-1 font-medium text-slate-700 select-none hover:text-slate-900 [&::-webkit-details-marker]:hidden">
        <ChevronIcon className="h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-90" />
        {summary}
      </summary>
      {children}
    </details>
  )
}
