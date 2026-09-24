import { ArrowUpRight } from 'lucide-react'
import { MarketMovement } from './MarketMovement'
import { NoticeForm } from './NoticeForm'
import { RecentResolutions } from './RecentResolutions'

export function DeskSidebar() {
  return <aside className="desk"><div className="desk-title"><h2>DESK</h2><span><i /> LIVE MARKET MOVEMENT <ArrowUpRight size={13} /></span></div><MarketMovement /><RecentResolutions /><NoticeForm /></aside>
}
