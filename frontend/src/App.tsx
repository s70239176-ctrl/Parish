import { useEffect, useState } from 'react'
import Board, { MarketData } from './screens/Board'
import Compose from './screens/Compose'
import Market from './screens/Market'
import { connectStudionet, getBalance, isConfigured, readJson, waitUntilFinal, writeTx } from './lib/genlayer'
import { genToWei, shortAddress, weiToGen } from './lib/format'

type View = 'board' | 'compose' | 'market'

export default function App() {
  const [view, setView] = useState<View>('board')
  const [markets, setMarkets] = useState<MarketData[]>([])
  const [selected, setSelected] = useState<MarketData | null>(null)
  const [wallet, setWallet] = useState(localStorage.getItem('parish.wallet') || '')
  const [balance, setBalance] = useState(0n)
  const [notice, setNotice] = useState('')

  const refresh = async () => {
    if (!isConfigured) return
    try {
      // IDs are deterministically m-1 through m-N. This avoids serializing a
      // GenLayer DynArray in a view call, which some Studio runtimes reject.
      const stats = await readJson('get_stats') as { market_count: string }
      const ids = Array.from({ length: Number(stats.market_count) }, (_, index) => `m-${index + 1}`)
      const all = await Promise.all(ids.map(id => readJson('get_market', [id])))
      setMarkets(all)
      setSelected(current => current ? all.find(market => market.id === current.id) || null : null)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Could not load markets.')
    }
  }

  useEffect(() => { refresh() }, [])
  useEffect(() => { if (wallet) getBalance(wallet).then(setBalance).catch(() => {}) }, [wallet])

  const connect = async () => {
    try {
      const account = await connectStudionet()
      setWallet(account)
      setBalance(await getBalance(account))
      setNotice('Wallet connected to Studionet.')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Could not connect wallet.')
    }
  }

  const transact = async (name: string, args: string[], amount?: string) => {
    if (['create_market', 'stake'].includes(name) && balance === 0n) throw new Error('Your wallet has no GEN. Use the Studio faucet before creating or staking.')
    const hash = await writeTx(name, args, amount === undefined ? undefined : genToWei(amount))
    setNotice(`Submitted ${hash}. Waiting for finalization…`)
    await waitUntilFinal(hash)
    setNotice('Finalized on Studionet.')
    await refresh()
    if (wallet) setBalance(await getBalance(wallet))
  }

  if (!isConfigured) return <main className="hard-error"><h1>Contract not configured.</h1><p>Set <code>VITE_CONTRACT_ADDRESS</code> to a deployed ParishMarkets address, then restart Vite.</p></main>
  const pick = (id: string) => { setSelected(markets.find(market => market.id === id) || null); setView('market') }

  return <main>
    <header><div><p className="mast">PARISH</p><p className="tag">The local odds desk</p></div><div className="network"><b>STUDIONET</b><span>chain 61999</span><a href={`https://explorer-studio.genlayer.com/address/${import.meta.env.VITE_CONTRACT_ADDRESS}`} target="_blank">{import.meta.env.VITE_CONTRACT_ADDRESS}</a></div><div className="wallet"><span>{shortAddress(wallet)}</span><b>{weiToGen(balance)} GEN</b><button onClick={connect}>Connect</button></div></header>
    <nav><button onClick={() => setView('board')}>Board</button><button onClick={() => setView('compose')}>Post a market</button><a href="https://studio.genlayer.com" target="_blank">Studio faucet ↗</a></nav>
    {notice && <p className="noticebar">{notice}</p>}
    {view === 'board' && <Board markets={markets} select={pick} />}
    {view === 'compose' && <Compose submit={async values => { await transact('create_market', values); setView('board') }} />}
    {view === 'market' && selected && <Market market={selected} action={transact} back={() => setView('board')} />}
  </main>
}
