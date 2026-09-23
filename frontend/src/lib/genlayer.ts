import { createClient } from 'genlayer-js'
import { studionet } from 'genlayer-js/chains'
import { ExecutionResult, TransactionHashVariant, TransactionStatus } from 'genlayer-js/types'

export const CONTRACT_ADDRESS = import.meta.env.VITE_CONTRACT_ADDRESS as string | undefined
export const isConfigured = Boolean(CONTRACT_ADDRESS && /^0x[a-fA-F0-9]{40}$/.test(CONTRACT_ADDRESS) && !/^0x0{40}$/i.test(CONTRACT_ADDRESS))
type Eip1193Provider = { request: (args: { method: string; params?: unknown[] }) => Promise<unknown> }
declare global { interface Window { ethereum?: Eip1193Provider } }

export const errorMessage = (error: unknown) => {
  if (error instanceof Error) return error.message
  if (typeof error === 'object' && error !== null) {
    const value = error as { shortMessage?: unknown; details?: unknown; message?: unknown; cause?: { message?: unknown } }
    for (const candidate of [value.shortMessage, value.details, value.message, value.cause?.message]) if (typeof candidate === 'string' && candidate) return candidate
    try { return JSON.stringify(error) } catch { return 'Unknown wallet or RPC error.' }
  }
  return String(error || 'Unknown wallet or RPC error.')
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
  try { return JSON.parse(String(await getReadClient().readContract({ address: CONTRACT_ADDRESS as `0x${string}`, functionName, args, transactionHashVariant: TransactionHashVariant.LATEST_FINAL }))) }
  catch (error) { throw new Error(`Could not read ${functionName}: ${errorMessage(error)}`) }
}

export async function writeTx(functionName: string, args: string[], valueWei?: bigint) {
  if (!isConfigured) throw new Error('Contract not configured.')
  await connectStudionet()
  try { return await getWriteClient().writeContract({ address: CONTRACT_ADDRESS as `0x${string}`, functionName, args, value: valueWei ?? 0n }) }
  catch (error) { throw new Error(`Could not submit ${functionName}: ${errorMessage(error)}`) }
}

export async function waitUntilFinal(hash: `0x${string}`) {
  const receipt = await getReadClient().waitForTransactionReceipt({ hash, status: TransactionStatus.FINALIZED })
  if (receipt.txExecutionResultName !== ExecutionResult.FINISHED_WITH_RETURN) throw new Error(`Transaction did not succeed: ${receipt.txExecutionResultName || receipt.statusName || 'unknown result'}.`)
  return receipt
}

export async function getBalance(wallet: string) { const balance = await window.ethereum?.request({ method: 'eth_getBalance', params: [wallet, 'latest'] }); return BigInt(String(balance || '0x0')) }
