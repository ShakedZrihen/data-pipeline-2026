// oxlint-disable react-hooks/exhaustive-deps -- `deps` comes from the caller,
// so no linter can verify it here; deferring that choice is the point of the hook.
import { useEffect, useState } from 'react'

export interface AsyncState<T> {
  data: T | null
  error: Error | null
  loading: boolean
}

/**
 * Runs `load` whenever `deps` change and aborts the in-flight request first,
 * so a fast typist's earlier search can never overwrite a later one's results.
 */
export function useAsync<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: unknown[],
): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ data: null, error: null, loading: true })

  useEffect(() => {
    const controller = new AbortController()
    setState((previous) => ({ ...previous, loading: true, error: null }))

    load(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ data, error: null, loading: false })
      },
      (cause: unknown) => {
        if (controller.signal.aborted) return
        setState({
          data: null,
          error: cause instanceof Error ? cause : new Error(String(cause)),
          loading: false,
        })
      },
    )

    return () => controller.abort()
  }, deps)

  return state
}
