import type { Market } from '@/types/market'
import { MarketCard } from './MarketCard'

export function MarketBoard({ markets }: { markets: Market[] }) {
  return <section className="market-grid" aria-label="Prediction markets">{markets.map((market) => <MarketCard key={market.id} market={market} />)}</section>
}
