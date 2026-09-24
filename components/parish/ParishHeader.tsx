import { ChevronDown, CircleUserRound, WalletCards } from 'lucide-react'

export function ParishHeader() {
  return <header className="masthead"><div className="brand"><div><b>PARISH</b><span>THE LOCAL ODDS DESK</span></div><i /><p>REAL QUESTIONS.<br />LOCAL PEOPLE.<br />LIVE ODDS.</p></div><div className="account-controls"><button><WalletCards size={21} /><small>WALLET</small><strong>0.312 <em>GEN</em></strong></button><button><CircleUserRound size={21} /><strong>0x7a3...9f2e</strong><ChevronDown size={14} /></button></div></header>
}
