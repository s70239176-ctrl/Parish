'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { markets } from '@/data/markets'
import { filterAndSort } from '@/lib/utils'
import { ParishHeader } from '@/components/parish/ParishHeader'
import { TopNav } from '@/components/parish/TopNav'
import { CategoryTabs } from '@/components/parish/CategoryTabs'
import { MarketBoard } from '@/components/parish/MarketBoard'
import { DeskSidebar } from '@/components/parish/DeskSidebar'
import { ParishFooter } from '@/components/parish/ParishFooter'

export default function Page() {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('ALL')
  const [sort, setSort] = useState('Most Active')
  const searchRef = useRef<HTMLInputElement>(null)
  useEffect(() => { const onKey = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); searchRef.current?.focus() } }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey) }, [])
  const visibleMarkets = useMemo(() => filterAndSort(markets, query, category, sort), [query, category, sort])
  return <main className="sheet"><ParishHeader /><TopNav search={query} onSearch={setQuery} inputRef={searchRef} /><CategoryTabs active={category} onActive={setCategory} sort={sort} onSort={setSort} /><div className="content"><div id="board"><MarketBoard markets={visibleMarkets} />{visibleMarkets.length === 0 && <p className="empty">No markets match that search.</p>}</div><DeskSidebar /></div><ParishFooter /></main>
}
