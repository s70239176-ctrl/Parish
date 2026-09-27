import { BarChart3, CalendarDays, MapPin, TrendingUp, Users } from 'lucide-react'
import type { Market } from '@/types/market'
import { ProbabilityBar } from './ProbabilityBar'

export function MarketCard({ market }: { market: Market }) {
  return <article className="market-card">
    <div className="card-top"><span className={`status ${market.status.toLowerCase()}`}>{market.status}</span><span className="category">{market.category}</span><span className="change"><TrendingUp size={13} /> {market.change}</span></div>
    <h2>{market.question}</h2>
    <div className="metadata"><span><CalendarDays size={13} />{market.date}</span><span><MapPin size={13} />{market.location}</span></div>
    <div className="prices"><div><label>YES</label><strong>{market.yes}¢</strong>{market.id !== 5 && <em className="up">(+{Math.max(5, Math.round(market.yes / 6))}%)</em>}</div><div><label>NO</label><strong>{market.no}¢</strong>{market.id !== 5 && <em className="down">(-{Math.max(5, Math.round(market.no / 3))}%)</em>}</div></div>
    <ProbabilityBar yes={market.yes} no={market.no} />
    <div className="card-stats"><span><Users size={13} /> {market.traders} traders</span><span><BarChart3 size={13} /> {market.volume} volume</span><span className="change">↗ {market.change}</span></div>
    <div className="card-bottom"><a href={`#market-${market.id}`}><MapPin size={14} /> {market.location}</a><a href={`#market-${market.id}`}>{market.status === 'RESOLVED' ? 'View result' : 'View market'} →</a></div>
  </article>
}
