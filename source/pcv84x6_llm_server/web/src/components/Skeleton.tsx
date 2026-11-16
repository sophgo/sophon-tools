/** Loading placeholders shaped like the page that is about to appear.
 *
 *  A lone spinner on an empty page reads as "nothing here"; a skeleton of the
 *  real layout says what is coming and keeps the page from jumping when the
 *  data lands. Pure CSS shimmer, disabled under prefers-reduced-motion by the
 *  global rule in styles.css.
 */

export function SkeletonLines({ lines = 3 }: { lines?: number }) {
  return (
    <div className="skel-lines" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skel" style={{ width: `${[92, 76, 58, 84, 66][i % 5]}%` }} />
      ))}
    </div>
  )
}

/** Title and subtitle stay real (they are static), the body is placeholders:
 *  a row of `stats` small cards, then `blocks` full-width cards. */
export default function PageSkeleton({
  title, sub, stats = 0, blocks = 2, label = '正在读取…',
}: { title: string; sub?: string; stats?: number; blocks?: number; label?: string }) {
  return (
    <div className="page-skeleton" role="status" aria-live="polite" aria-label={label} data-testid="page-skeleton">
      <h1>{title}</h1>
      {sub && <p className="sub">{sub}</p>}
      {stats > 0 && (
        <div className={`grid c${Math.min(stats, 4)}`}>
          {Array.from({ length: stats }, (_, i) => (
            <div key={i} className="card tight">
              <span className="skel skel-label" />
              <span className="skel skel-metric" />
              <span className="skel skel-note" />
            </div>
          ))}
        </div>
      )}
      {Array.from({ length: blocks }, (_, i) => (
        <div key={i} className="card skel-card">
          <span className="skel skel-title" />
          <SkeletonLines lines={i === 0 ? 4 : 3} />
        </div>
      ))}
      <span className="skel-status"><span className="spin" /> {label}</span>
    </div>
  )
}
