/** Minimal SVG sparkline; avoids pulling a charting library onto an offline box. */
export default function Sparkline({
  values, height = 44, width = 220, color = 'var(--accent)',
}: { values: number[]; height?: number; width?: number; color?: string }) {
  if (!values.length) {
    return <div className="note" style={{ height }}>暂无数据</div>
  }
  // A single sample would draw a zero-length polyline -- an invisible chart that
  // reads as "no data". Draw a flat segment plus a dot instead.
  if (values.length === 1) {
    const y = height / 2
    return (
      <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <line x1="0" y1={y} x2={width} y2={y} stroke={color} strokeWidth="1.6"
              vectorEffect="non-scaling-stroke" opacity="0.5" />
        <circle cx={width / 2} cy={y} r="3" fill={color} />
      </svg>
    )
  }
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const span = max - min || 1
  const step = values.length > 1 ? width / (values.length - 1) : width
  const pts = values
    .map((v, i) => `${(i * step).toFixed(1)},${(height - ((v - min) / span) * (height - 4) - 2).toFixed(1)}`)
    .join(' ')
  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
