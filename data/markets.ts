import type { Market } from '@/types/market'

export const markets: Market[] = [
  { id: 1, status: 'LIVE', category: 'CIVIC', change: '+6.4%', question: 'Will Parish display this first live market before the next hour?', date: 'Dec 31, 2025 · 5:00 PM', location: 'Parish HQ', yes: 68, no: 32, traders: 142, volume: '$8.4K' },
  { id: 2, status: 'OPEN', category: 'FOOD', change: '+2.1%', question: 'Will the taco truck be on 5th by 12:30?', date: 'Sep 24, 2025 · 12:30 PM', location: '5th & Pine', yes: 72, no: 28, traders: 96, volume: '$6.1K' },
  { id: 3, status: 'LIVE', category: 'CIVIC', change: '+3.7%', question: 'Will the corner store restock ice before noon?', date: 'Sep 24, 2025 · 12:00 PM', location: 'Corner Store', yes: 55, no: 45, traders: 73, volume: '$6.2K' },
  { id: 4, status: 'RESOLVED', category: 'SPORTS', change: '+0.0%', question: 'Will the Eagles win their next game?', date: 'Sep 21, 2025 · 4:25 PM', location: 'Lincoln Financial Field', yes: 64, no: 36, traders: 512, volume: '$28.4K', resolved: 'YES' },
  { id: 5, status: 'VOID', category: 'WEIRD', change: '—', question: 'Will there be a rainbow over Parish before Friday?', date: 'Sep 26, 2025 · 6:00 PM', location: 'Parish', yes: 41, no: 59, traders: 28, volume: '$1.2K' },
  { id: 6, status: 'LIVE', category: 'GIT', change: '+9.8%', question: 'Will the library be open on Saturday?', date: 'Sep 27, 2025 · 10:00 AM', location: 'Riverside Library', yes: 83, no: 17, traders: 201, volume: '$11.7K' },
]
