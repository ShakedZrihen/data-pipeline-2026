// Mirrors the Pydantic response models in salim/api/schemas.py.
//
// Pydantic serializes Decimal as a JSON string to avoid precision loss, so
// every money/quantity field arrives as text and must go through toNumber().
export type Decimal = string | number

export interface PriceSummary {
  min_price: Decimal
  max_price: Decimal
  store_count: number
  chain_count: number
}

export interface Product {
  product_id: string
  gtin: string | null
  slug: string | null
  display_name: string | null
  manufacturer: string | null
  updated_at: string | null
  // Only /products carries this. /products/{id} serves the full price lists
  // instead, so it is absent there rather than null.
  price_summary?: PriceSummary | null
}

export interface Price {
  provider: string
  chain_name: string | null
  store_id: string
  item_name: string | null
  price: Decimal
  update_time: string | null
}

export interface PromotionItem {
  item_code: string
  item_name: string | null
  discount_type: number | null
  min_qty: Decimal | null
  max_qty: Decimal | null
  discount_price: Decimal | null
  discounted_price_per_mida: Decimal | null
}

export interface Promotion {
  provider: string
  chain_name: string | null
  store_id: string
  promotion_id: string
  description: string | null
  start_time: string | null
  end_time: string | null
  items: PromotionItem[]
}

export interface ProductPromotions {
  has_promotion: boolean
  promotions: Promotion[]
}

export interface OpeningHour {
  weekday: number
  interval_index: number
  opens_at: string
  closes_at: string
}

export interface Branch {
  chain_id: string
  branch_id: string
  name: string | null
  city: string | null
  address: string | null
  latitude: number | null
  longitude: number | null
  timezone: string
  is_active: boolean
  phone: string | null
  city_code: string | null
  store_type: string | null
  fields_not_provided: string[] | null
  enrichment_match: string | null
  enriched_at: string | null
  opening_hours: OpeningHour[]
}

export interface Store {
  chain_id: string
  name: string
  slug: string | null
}

export interface StoreDetail extends Store {
  branches: Branch[]
}

export interface StoreList {
  items: Store[]
  total: number
  limit: number
  offset: number
}
