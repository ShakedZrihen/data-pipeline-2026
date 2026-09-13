interface StatusProps {
  kind: 'loading' | 'error' | 'empty'
  title: string
  detail?: string
}

export function Status({ kind, title, detail }: StatusProps) {
  return (
    <div className={`status status--${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      {kind === 'loading' && <span className="spinner" aria-hidden="true" />}
      <p className="status__title">{title}</p>
      {detail && <p className="status__detail">{detail}</p>}
    </div>
  )
}
