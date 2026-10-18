import type { ReactNode } from 'react'
import { AlertIcon } from './icons'

/** Shared input styling: 44 px tall, 16 px text on phones (no iOS focus zoom). */
export const INPUT_CLASS =
  'h-11 w-full min-w-0 rounded-md border border-slate-300 bg-white px-3 text-base text-slate-900 shadow-xs transition ' +
  'placeholder:text-slate-400 hover:border-slate-400 focus:border-brand-600 focus:outline-none focus:ring-3 ' +
  'focus:ring-brand-600/20 aria-invalid:border-red-500 lg:text-sm'

interface Props {
  label: string
  htmlFor: string
  error?: string
  children: ReactNode
}

export function Field({ label, htmlFor, error, children }: Props) {
  return (
    <div className="min-w-0">
      <label htmlFor={htmlFor} className="mb-1.5 block text-sm font-medium text-slate-700">
        {label}
      </label>
      {children}
      <FieldError id={`${htmlFor}-error`} message={error} />
    </div>
  )
}

export function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null
  return (
    <p id={id} className="mt-1.5 flex items-start gap-1.5 text-sm text-red-700">
      <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
      {message}
    </p>
  )
}
