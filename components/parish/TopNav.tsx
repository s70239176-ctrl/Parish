import { ExternalLink } from 'lucide-react'
import { SearchBar } from './SearchBar'

export function TopNav({ search, onSearch, inputRef }: { search: string; onSearch: (value: string) => void; inputRef: React.RefObject<HTMLInputElement | null> }) {
  return <nav className="top-nav" aria-label="Primary"><div><a className="active" href="#board">Board</a><a href="#notice">Post a market</a><a href="https://studio.genlayer.com" target="_blank">Studio faucet <ExternalLink size={12} /></a></div><SearchBar value={search} onChange={onSearch} inputRef={inputRef} /></nav>
}
