import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = { title: 'Parish — The Local Odds Desk', description: 'Local predictions. Real impact.' }

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>
}
