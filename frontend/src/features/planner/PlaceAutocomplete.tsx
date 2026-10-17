import { useEffect, useId, useRef, useState } from 'react'
import { usePlaceSearch } from '../../api/queries'
import type { Place } from '../../api/types'

interface Props {
  label: string
  placeholder: string
  value: Place | null
  onChange: (place: Place | null) => void
  error?: string
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return debounced
}

export function PlaceAutocomplete({ label, placeholder, value, onChange, error }: Props) {
  const id = useId()
  const listId = `${id}-list`
  const [text, setText] = useState(value?.label ?? '')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  // Keep the text in sync when the parent sets a place (e.g. a demo preset).
  const [syncedValue, setSyncedValue] = useState(value)
  if (value !== syncedValue) {
    setSyncedValue(value)
    if (value) setText(value.label)
  }

  const query = useDebounced(text, 250)
  const search = usePlaceSearch(open && query !== value?.label ? query : '')
  const results = search.data ?? []

  const choose = (place: Place) => {
    onChange(place)
    setText(place.label)
    setOpen(false)
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || results.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => (i + 1) % results.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => (i - 1 + results.length) % results.length)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      choose(results[Math.min(active, results.length - 1)])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const showList = open && text.trim().length >= 2 && text !== value?.label

  return (
    <div className="relative">
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-slate-600">
        {label}
      </label>
      <input
        ref={inputRef}
        id={id}
        type="text"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-invalid={!!error}
        autoComplete="off"
        placeholder={placeholder}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          setActive(0)
          setOpen(true)
          if (value) onChange(null)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={onKeyDown}
        className={`w-full rounded-md border bg-white px-3 py-2 text-sm shadow-sm outline-none transition focus:ring-2 focus:ring-sky-500 ${
          error ? 'border-red-400' : 'border-slate-300'
        }`}
      />
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
      {showList && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-md border border-slate-200 bg-white py-1 text-sm shadow-lg"
        >
          {search.isFetching && results.length === 0 && <li className="px-3 py-2 text-slate-500">Searching…</li>}
          {search.isError && <li className="px-3 py-2 text-red-600">Place search is unavailable right now.</li>}
          {!search.isFetching && !search.isError && results.length === 0 && (
            <li className="px-3 py-2 text-slate-500">No matches in North America.</li>
          )}
          {results.map((place, i) => (
            <li
              key={`${place.label}-${place.lat}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault()
                choose(place)
              }}
              onMouseEnter={() => setActive(i)}
              className={`cursor-pointer px-3 py-2 ${i === active ? 'bg-sky-50 text-sky-900' : 'text-slate-700'}`}
            >
              {place.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
