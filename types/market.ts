export type MarketStatus = 'LIVE' | 'OPEN' | 'RESOLVED' | 'VOID'
export type Category = 'CIVIC' | 'FOOD' | 'SPORTS' | 'WEIRD' | 'GIT'

export type Market = {
  id: number
  status: MarketStatus
  category: Category
  change: string
  question: string
  date: string
  location: string
  yes: number
  no: number
  traders: number
  volume: string
  resolved?: 'YES' | 'NO'
}
