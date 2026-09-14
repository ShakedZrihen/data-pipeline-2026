import { useEffect, useMemo, useState } from 'react'
import { describeBranch, loadBranches, type BranchIndex } from '../api/branches'
import type { Price } from '../api/types'
import { formatDateTime, formatPrice, toNumber } from '../lib/format'

/**
 * Branch ids restart from 001 in every chain, so each chain needs its own
 * index. Names arrive after the prices and fill in when they do.
 */
function useBranchIndexes(prices: Price[]): Map<string, BranchIndex> {
  const providers = useMemo(
    () => [...new Set(prices.map((price) => price.provider))].sort(),
    [prices],
  )
  const providerKey = providers.join(',')
  const [indexes, setIndexes] = useState<Map<string, BranchIndex>>(new Map())

  useEffect(() => {
    if (providers.length === 0) return
    let active = true

    Promise.all(
      providers.map((provider) =>
        loadBranches(provider).then((index) => [provider, index] as const),
      ),
    ).then((results) => {
      if (active) setIndexes(new Map(results))
    })

    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerKey])

  return indexes
}

/** `prices` must already be sorted cheapest first; the ends are labelled as such. */
export function PriceTable({ prices }: { prices: Price[] }) {
  const branchIndexes = useBranchIndexes(prices)

  // Marking by value, not by position: several branches usually share the
  // cheapest price, and tagging only the first of them would be a lie.
  const amounts = prices.map((price) => toNumber(price.price)).filter((amount) => amount !== null)
  const cheapest = amounts.length > 0 ? Math.min(...amounts) : null
  const priciest = amounts.length > 0 ? Math.max(...amounts) : null
  const hasSpread = cheapest !== null && priciest !== null && priciest > cheapest

  function extremeOf(price: Price): 'low' | 'high' | null {
    if (!hasSpread) return null
    const amount = toNumber(price.price)
    if (amount === cheapest) return 'low'
    if (amount === priciest) return 'high'
    return null
  }

  return (
    <table className="table">
      <thead>
        <tr>
          <th scope="col" className="cell--rank">
            #
          </th>
          <th scope="col">רשת</th>
          <th scope="col">סניף</th>
          <th scope="col">השם ברשת</th>
          <th scope="col">מחיר</th>
          <th scope="col">עודכן במקור</th>
        </tr>
      </thead>
      <tbody>
        {prices.map((price, index) => {
          const extreme = extremeOf(price)
          return (
            <tr
              // Two SKUs of one product can share a store, so the position is
              // the only stable key here.
              key={`${price.provider}:${price.store_id}:${index}`}
              className={extreme ? `row--${extreme}` : undefined}
            >
              <td className="cell--rank">{index + 1}</td>
              <td>{price.chain_name ?? price.provider}</td>
              <td>
                {describeBranch(branchIndexes.get(price.provider)?.find(price.store_id), price.store_id)}
              </td>
              <td className="cell--name">{price.item_name ?? '—'}</td>
              <td className="cell--price">
                {formatPrice(price.price)}
                {extreme === 'low' && <span className="tag tag--low">הזול ביותר</span>}
                {extreme === 'high' && <span className="tag tag--high">היקר ביותר</span>}
              </td>
              <td className="cell--muted">{formatDateTime(price.update_time)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
