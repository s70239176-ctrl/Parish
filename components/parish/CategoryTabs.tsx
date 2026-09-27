import { ChevronDown } from 'lucide-react'
import { categories } from '@/lib/utils'

export function CategoryTabs({ active, onActive, sort, onSort }: { active: string; onActive: (value: string) => void; sort: string; onSort: (value: string) => void }) {
  return <div className="category-row"><div className="tabs" role="tablist">{categories.map((category) => <button key={category} role="tab" aria-selected={active === category} className={active === category ? 'selected' : ''} onClick={() => onActive(category)}>{category[0] + category.slice(1).toLowerCase()}</button>)}</div><label className="sort">Sort by: <select value={sort} onChange={(e) => onSort(e.target.value)}><option>Most Active</option><option>Highest Probability</option><option>Lowest Probability</option><option>Most Traders</option></select><ChevronDown size={14} /></label></div>
}
