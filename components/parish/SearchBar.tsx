import { Search } from 'lucide-react'

export function SearchBar({ value, onChange, inputRef }: { value: string; onChange: (value: string) => void; inputRef: React.RefObject<HTMLInputElement | null> }) {
  return <label className="search"><Search size={15} /><input ref={inputRef} value={value} onChange={(event) => onChange(event.target.value)} placeholder="Search markets, places, topics..." aria-label="Search markets" /><kbd>⌘ K</kbd></label>
}
