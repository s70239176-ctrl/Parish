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
// `date.toISOString()` is UTC, but a `datetime-local` input's `defaultValue` is read back
// as the user's LOCAL wall-clock time. Labeling a UTC instant as local silently shifts it
// by the timezone offset, which could put the default under the contract's 5-minute minimum
// for anyone east of UTC. This formats in local time instead so the two stay in sync.
export const toLocalDateTimeInput = (date: Date) => {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}
export const timeLeft = (unix: string) => { const s = Number(unix) - Math.floor(Date.now() / 1000); if (s <= 0) return 'deadline passed'; return s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m left` : `${Math.floor(s / 60)}m left` }
