export function ProbabilityBar({ yes, no }: { yes: number; no: number }) {
  return <div className="probability" aria-label={`Yes ${yes} percent, No ${no} percent`}><span style={{ width: `${yes}%` }}>{yes}%</span><span>{no}%</span></div>
}
