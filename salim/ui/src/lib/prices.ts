import type { Price, PriceSummary } from '../api/types'
import { toNumber } from './format'

export interface Spread {
  min: number
  max: number
  diff: number
  percent: number
}

/**
 * One ascending list of every price we fetched, cheapest first.
 *
 * The API only exposes the N cheapest and N priciest separately, so both are
 * requested and stitched back together; the two overlap completely whenever a
 * product sells in fewer stores than the limit.
 */
export function mergePriceRows(lowest: Price[], highest: Price[]): Price[] {
  const seen = new Map<string, Price>()
  for (const row of [...lowest, ...highest]) {
    // A store can price two SKUs of the same catalog product, and the endpoint
    // does not return item_code, so the visible fields are the row's identity.
    seen.set([row.provider, row.store_id, row.item_name, row.price].join('\u0000'), row)
  }
  return [...seen.values()].sort(
    (a, b) => (toNumber(a.price) ?? Infinity) - (toNumber(b.price) ?? Infinity),
  )
}

/** Same gap, from the summary the list endpoint already returns. */
export function summarySpread(summary: PriceSummary): Spread | null {
  const min = toNumber(summary.min_price)
  const max = toNumber(summary.max_price)
  if (min === null || max === null || max <= min) return null
  return { min, max, diff: max - min, percent: ((max - min) / min) * 100 }
}

/**
 * Gap between the cheapest and priciest current price. Null when the product
 * sells at one price everywhere, or is priced in only one store.
 */
export function priceSpread(lowest: Price[], highest: Price[]): Spread | null {
  const min = toNumber(lowest[0]?.price)
  const max = toNumber(highest[0]?.price)
  if (min === null || max === null || max <= min) return null
  return { min, max, diff: max - min, percent: ((max - min) / min) * 100 }
}
