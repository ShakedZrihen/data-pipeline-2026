import type {
  Price,
  Product,
  ProductPromotions,
  StoreDetail,
  StoreList,
} from './types'

// Defaults to the dev-server proxy defined in vite.config.ts, and to the nginx
// /api location in a container build. Point it at the deployed API (and add
// that origin to the API's UI_ORIGINS) when the two are hosted separately.
//
// `||`, not `??`: an unset Docker ARG still reaches the build as an empty
// string, which must mean "not configured" rather than "same origin".
const BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '')

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

type QueryValue = string | number | boolean | undefined

async function get<T>(
  path: string,
  params: Record<string, QueryValue> = {},
  signal?: AbortSignal,
): Promise<T> {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') query.set(key, String(value))
  }
  const suffix = query.toString()
  const response = await fetch(`${BASE_URL}${path}${suffix ? `?${suffix}` : ''}`, {
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!response.ok) {
    throw new ApiError(response.status, await describeFailure(response))
  }
  return (await response.json()) as T
}

async function describeFailure(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // A non-JSON error body (a proxy or gateway page) is still worth reporting.
  }
  return `${response.status} ${response.statusText}`
}

export interface ProductQuery {
  q?: string
  hasPromotion?: boolean
  limit?: number
  offset?: number
}

export function listProducts(query: ProductQuery, signal?: AbortSignal): Promise<Product[]> {
  return get<Product[]>(
    '/products',
    {
      q: query.q,
      has_promotion: query.hasPromotion,
      limit: query.limit,
      offset: query.offset,
    },
    signal,
  )
}

export function getProduct(productId: string, signal?: AbortSignal): Promise<Product> {
  return get<Product>(`/products/${encodeURIComponent(productId)}`, {}, signal)
}

export function getProductPrices(
  productId: string,
  order: 'lowest' | 'highest',
  limit: number,
  signal?: AbortSignal,
): Promise<Price[]> {
  return get<Price[]>(
    `/products/${encodeURIComponent(productId)}/prices/${order}`,
    { limit },
    signal,
  )
}

export function getProductPromotions(
  productId: string,
  activeOnly: boolean,
  signal?: AbortSignal,
): Promise<ProductPromotions> {
  return get<ProductPromotions>(
    `/products/${encodeURIComponent(productId)}/promotions`,
    { active_only: activeOnly },
    signal,
  )
}

export function listStores(signal?: AbortSignal): Promise<StoreList> {
  return get<StoreList>('/stores', { limit: 100 }, signal)
}

export function getStore(chainId: string, signal?: AbortSignal): Promise<StoreDetail> {
  return get<StoreDetail>(`/stores/${encodeURIComponent(chainId)}`, {}, signal)
}
