interface Props<T extends string | number> {
  options: readonly T[]
  value: T
  onChange: (value: T) => void
  label: (value: T) => string
  /** Accessible name of the group. */
  ariaLabel?: string
  ariaLabelledBy?: string
  className?: string
}

/** A row of toggle buttons (aria-pressed), 40 px tall, for small sets of exclusive options. */
export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
  ariaLabel,
  ariaLabelledBy,
  className = '',
}: Props<T>) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      className={`flex rounded-md border border-slate-300 bg-slate-100 p-0.5 ${className}`}
    >
      {options.map((option) => {
        const active = option === value
        return (
          <button
            key={String(option)}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option)}
            className={`h-10 min-w-0 flex-1 rounded-[5px] px-2.5 text-sm font-medium transition ${
              active ? 'bg-white text-slate-900 shadow-sm ring-1 ring-slate-300' : 'text-slate-600 hover:bg-white/60 hover:text-slate-900'
            }`}
          >
            {label(option)}
          </button>
        )
      })}
    </div>
  )
}
