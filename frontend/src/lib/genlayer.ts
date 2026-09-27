import { createClient } from 'genlayer-js'
import { studionet } from 'genlayer-js/chains'
import { ExecutionResult, Hash, TransactionHashVariant, TransactionStatus } from 'genlayer-js/types'

export type { Hash }

export const CONTRACT_ADDRESS = import.meta.env.VITE_CONTRACT_ADDRESS as string | undefined
export const isConfigured = Boolean(CONTRACT_ADDRESS && /^0x[a-fA-F0-9]{40}$/.test(CONTRACT_ADDRESS) && !/^0x0{40}$/i.test(CONTRACT_ADDRESS))
type Eip1193Provider = {
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>
  on?: (event: string, handler: (...args: unknown[]) => void) => void
  removeListener?: (event: string, handler: (...args: unknown[]) => void) => void
}
declare global { interface Window { ethereum?: Eip1193Provider } }

export const EXPLORER_BASE = 'https://explorer-studio.genlayer.com'
export const explorerTxUrl = (hash: string) => `${EXPLORER_BASE}/tx/${hash}`
export const explorerAddressUrl = (address: string) => `${EXPLORER_BASE}/address/${address}`

export type TxOutcome = 'pending' | 'finalized' | 'rejected' | 'failed' | 'timeout'
export type TxResult = { hash: Hash; outcome: TxOutcome; detail: string }

export const errorMessage = (error: unknown) => {
  if (error instanceof Error) return error.message
  if (typeof error === 'object' && error !== null) {
    const value = error as { shortMessage?: unknown; details?: unknown; message?: unknown; cause?: { message?: unknown } }
    for (const candidate of [value.shortMessage, value.details, value.message, value.cause?.message]) if (typeof candidate === 'string' && candidate) return candidate
    try { return JSON.stringify(error) } catch { return 'Unknown wallet or RPC error.' }
  }
  return String(error || 'Unknown wallet or RPC error.')
}

// Network/RPC failures (dropped connection, DNS hiccup, node restart) are worth
// retrying with backoff; a contract-level rejection (bad input, reverted write)
// is not — retrying it just re-triggers the same deterministic failure.
const isTransientRpcError = (error: unknown) => {
  const message = errorMessage(error).toLowerCase()
  return ['network', 'fetch failed', 'timeout', 'timed out', 'econnreset', 'econnrefused', 'failed to fetch', '429', '503', '502', 'rate limit', 'disconnected'].some(needle => message.includes(needle))
}

async function withRpcRetry<T>(fn: () => Promise<T>, attempts = 3): Promise<T> {
  let lastError: unknown
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try { return await fn() }
    catch (error) {
      lastError = error
      if (attempt === attempts || !isTransientRpcError(error)) throw error
      await new Promise(resolve => setTimeout(resolve, 300 * attempt))
    }
  }
  throw lastError
}

const walletAddress = () => localStorage.getItem('parish.wallet') as `0x${string}` | null
export const getReadClient = () => createClient({ chain: studionet })
export const getWriteClient = () => { const account = walletAddress(); if (!window.ethereum || !account) throw new Error('Connect a MetaMask wallet first.'); return createClient({ chain: studionet, account, provider: window.ethereum }) }

async function switchToStudionet(provider: Eip1193Provider) {
  const chainId = '0xf22f'
  if (await provider.request({ method: 'eth_chainId' }) === chainId) return
  try { await provider.request({ method: 'wallet_switchEthereumChain', params: [{ chainId }] }) }
  catch (error) {
    const code = typeof error === 'object' && error !== null ? (error as { code?: number }).code : undefined
    if (code !== 4902) throw error
    await provider.request({ method: 'wallet_addEthereumChain', params: [{ chainId, chainName: 'Studionet', nativeCurrency: { name: 'GEN', symbol: 'GEN', decimals: 18 }, rpcUrls: ['https://studio.genlayer.com/api'], blockExplorerUrls: ['https://explorer-studio.genlayer.com'] }] })
  }
}

export async function connectStudionet() {
  if (!window.ethereum) throw new Error('MetaMask is required for Studionet writes.')
  await switchToStudionet(window.ethereum)
  const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' }) as string[]
  if (!accounts[0]) throw new Error('MetaMask did not return an account.')
  localStorage.setItem('parish.wallet', accounts[0].toLowerCase())
  return accounts[0]
}

export async function readJson(functionName: string, args: string[] = []) {
  if (!isConfigured) throw new Error('Contract not configured.')
  try {
    return JSON.parse(String(await withRpcRetry(() => getReadClient().readContract({ address: CONTRACT_ADDRESS as `0x${string}`, functionName, args, transactionHashVariant: TransactionHashVariant.LATEST_FINAL }))))
  } catch (error) { throw new Error(`Could not read ${functionName}: ${errorMessage(error)}`) }
}

export async function writeTx(functionName: string, args: string[], valueWei?: bigint) {
  if (!isConfigured) throw new Error('Contract not configured.')
  await connectStudionet()
  try { return await getWriteClient().writeContract({ address: CONTRACT_ADDRESS as `0x${string}`, functionName, args, value: valueWei ?? 0n }) }
  catch (error) { throw new Error(`Could not submit ${functionName}: ${errorMessage(error)}`) }
}

const FINALIZATION_TIMEOUT_MS = 120_000

export async function waitUntilFinal(hash: Hash): Promise<TxResult> {
  let receipt: Awaited<ReturnType<ReturnType<typeof getReadClient>['waitForTransactionReceipt']>>
  try {
    receipt = await Promise.race([
      withRpcRetry(() => getReadClient().waitForTransactionReceipt({ hash, status: TransactionStatus.FINALIZED })),
      new Promise<never>((_, reject) => setTimeout(() => reject(new Error('__timeout__')), FINALIZATION_TIMEOUT_MS)),
    ])
  } catch (error) {
    if (errorMessage(error) === '__timeout__') return { hash, outcome: 'timeout', detail: `Still waiting for finalization after ${FINALIZATION_TIMEOUT_MS / 1000}s — it may still land.` }
    return { hash, outcome: 'failed', detail: errorMessage(error) }
  }
  const resultName = receipt.txExecutionResultName || receipt.statusName || 'unknown result'
  if (receipt.txExecutionResultName === ExecutionResult.FINISHED_WITH_RETURN) return { hash, outcome: 'finalized', detail: resultName }
  const rejected = /reject/i.test(resultName)
  return { hash, outcome: rejected ? 'rejected' : 'failed', detail: resultName }
}

export function watchWalletEvents(handlers: { onAccountsChanged?: (accounts: string[]) => void; onChainChanged?: (chainId: string) => void }) {
  const provider = window.ethereum
  if (!provider?.on) return () => {}
  const accountsHandler = (...args: unknown[]) => handlers.onAccountsChanged?.((args[0] as string[]) || [])
  const chainHandler = (...args: unknown[]) => handlers.onChainChanged?.(args[0] as string)
  provider.on('accountsChanged', accountsHandler)
  provider.on('chainChanged', chainHandler)
  return () => { provider.removeListener?.('accountsChanged', accountsHandler); provider.removeListener?.('chainChanged', chainHandler) }
}

export async function getBalance(wallet: string) { const balance = await window.ethereum?.request({ method: 'eth_getBalance', params: [wallet, 'latest'] }); return BigInt(String(balance || '0x0')) }
