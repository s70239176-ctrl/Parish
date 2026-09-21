export const weiToGen = (value: string | bigint) => {
  const n = BigInt(value || 0)
  const whole = n / 10n ** 18n
  const fraction = (n % 10n ** 18n).toString().padStart(18, '0').slice(0, 3).replace(/0+$/, '')
  return `${whole}${fraction ? `.${fraction}` : ''}`
}
export const genToWei = (value: string) => {
  if (!/^\d+(\.\d{0,18})?$/.test(value)) throw new Error('Enter a GEN amount with up to 18 decimal places.')
  const [whole, fraction = ''] = value.split('.')
  return BigInt(whole + fraction.padEnd(18, '0'))
}
export const shortAddress = (value?: string) => value ? `${value.slice(0, 8)}…${value.slice(-6)}` : 'No wallet'
export const timeLeft = (unix: string) => { const s = Number(unix) - Math.floor(Date.now() / 1000); if (s <= 0) return 'deadline passed'; return s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m left` : `${Math.floor(s / 60)}m left` }
