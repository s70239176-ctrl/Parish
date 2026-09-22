import { createClient } from 'genlayer-js'
import { studionet } from 'genlayer-js/chains'
import { TransactionStatus } from 'genlayer-js/types'
export const CONTRACT_ADDRESS = import.meta.env.VITE_CONTRACT_ADDRESS as string | undefined
export const isConfigured = Boolean(CONTRACT_ADDRESS && /^0x[a-fA-F0-9]{40}$/.test(CONTRACT_ADDRESS) && !/^0x0{40}$/i.test(CONTRACT_ADDRESS))
declare global { interface Window { ethereum?: { request: (args: { method: string; params?: unknown[] }) => Promise<unknown> } } }
export const errorMessage = (error: unknown) => {
  if (error instanceof Error) return error.message
  if (typeof error === 'object' && error !== null) {
    const candidate = error as { message?: unknown; details?: unknown; shortMessage?: unknown; cause?: { message?: unknown } }
    for (const value of [candidate.shortMessage, candidate.details, candidate.message, candidate.cause?.message]) if (typeof value === 'string' && value) return value
    try { return JSON.stringify(error) } catch { return 'Unknown wallet or RPC error.' }
  }
  return String(error || 'Unknown wallet or RPC error.')
}
const savedAddress = () => localStorage.getItem('parish.wallet') as `0x${string}` | null
export const getReadClient = () => createClient({ chain: studionet })
export const getWriteClient = () => { const account = savedAddress(); if (!window.ethereum || !account) throw new Error('Connect a MetaMask wallet first.'); return createClient({ chain: studionet, account, provider: window.ethereum }) }
export async function connectStudionet() { if (!window.ethereum) throw new Error('MetaMask is required for Studionet writes.'); const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' }) as string[]; const chain = await window.ethereum.request({ method: 'eth_chainId' }) as string; if (parseInt(chain, 16) !== 61999) throw new Error('Switch MetaMask to Studionet (chain 61999).'); if (!accounts[0]) throw new Error('MetaMask did not return an account.'); localStorage.setItem('parish.wallet', accounts[0].toLowerCase()); await getWriteClient().connect('studionet'); return accounts[0] }
export async function readJson(functionName: string, args: string[] = []) {
  if (!isConfigured) throw new Error('Contract not configured.')
  try {
    const data = await getReadClient().readContract({ address: CONTRACT_ADDRESS as `0x${string}`, functionName, args })
    return JSON.parse(String(data))
  } catch (error) {
    const message = errorMessage(error)
    throw new Error(`Could not read ${functionName}: ${message}`)
  }
}
export async function writeTx(functionName: string, args: string[], valueWei?: bigint) { if (!isConfigured) throw new Error('Contract not configured.'); await connectStudionet(); const client = getWriteClient(); try { return client.writeContract({ address: CONTRACT_ADDRESS as `0x${string}`, functionName, args, value: valueWei ?? 0n }) } catch (error) { throw new Error(`Could not submit ${functionName}: ${errorMessage(error)}`) } }
export async function waitUntilFinal(hash: `0x${string}`) { const receipt = await getReadClient().waitForTransactionReceipt({ hash, status: TransactionStatus.FINALIZED }); if (receipt.txExecutionResultName !== 'FINISHED_WITH_RETURN') throw new Error(`Transaction did not succeed: ${receipt.txExecutionResultName || receipt.statusName || 'unknown result'}.`); return receipt }
export async function getBalance(wallet: string) { const balance = await window.ethereum?.request({ method: 'eth_getBalance', params: [wallet, 'latest'] }); return BigInt(String(balance || '0x0')) }
