import type { Category, Market } from '@/types/market'

export const categories: Array<'ALL' | 'NEAR' | Category> = ['ALL', 'NEAR', 'GIT', 'CIVIC', 'WEIRD']

export function filterAndSort(items: Market[], query: string, category: string, sort: string) {
  const needle = query.trim().toLowerCase()
  const filtered = items.filter((market) => {
    const matches = !needle || [market.question, market.category, market.location].join(' ').toLowerCase().includes(needle)
    return matches && (category === 'ALL' || category === 'NEAR' || market.category === category)
  })
  return [...filtered].sort((a, b) => {
    if (sort === 'Highest Probability') return b.yes - a.yes
    if (sort === 'Lowest Probability') return a.yes - b.yes
    if (sort === 'Most Traders') return b.traders - a.traders
    return Number.parseFloat(b.volume.replace(/[$K]/g, '')) - Number.parseFloat(a.volume.replace(/[$K]/g, ''))
  })
}
