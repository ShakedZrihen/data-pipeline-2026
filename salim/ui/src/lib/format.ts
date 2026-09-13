import type { Decimal } from '../api/types'

const shekels = new Intl.NumberFormat('he-IL', {
  style: 'currency',
  currency: 'ILS',
  minimumFractionDigits: 2,
})

const dateTime = new Intl.DateTimeFormat('he-IL', {
  dateStyle: 'short',
  timeStyle: 'short',
  timeZone: 'Asia/Jerusalem',
})

const dateOnly = new Intl.DateTimeFormat('he-IL', { dateStyle: 'short', timeZone: 'Asia/Jerusalem' })

export function toNumber(value: Decimal | null | undefined): number | null {
  if (value === null || value === undefined) return null
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function formatPrice(value: Decimal | null | undefined): string {
  const parsed = toNumber(value)
  return parsed === null ? '—' : shekels.format(parsed)
}

export function formatQuantity(value: Decimal | null | undefined): string {
  const parsed = toNumber(value)
  return parsed === null ? '—' : String(parsed)
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime()) ? '—' : dateTime.format(parsed)
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime()) ? '—' : dateOnly.format(parsed)
}

export interface ProductIdentity {
  label: string
  hint: string
  comparable: boolean
}

/**
 * `product_id` encodes how comparable a product is: the loader mints
 * `gtin:<barcode>` for real barcode items (item_type 1) and
 * `chain:<chainId>:<itemCode>` for codes a chain invented for itself.
 */
export function describeProductId(productId: string): ProductIdentity {
  if (productId.startsWith('gtin:')) {
    return {
      label: 'ברקוד',
      hint: 'מוצר עם ברקוד תקני — ניתן להשוות את מחירו בין כל הרשתות',
      comparable: true,
    }
  }
  if (productId.startsWith('chain:')) {
    return {
      label: 'קוד רשת',
      hint: 'קוד פנימי של רשת אחת — אין לו מקבילה בשאר הרשתות',
      comparable: false,
    }
  }
  return { label: 'לא מזוהה', hint: 'מזהה בפורמט לא מוכר', comparable: false }
}

const DISCOUNT_TYPES: Record<number, string> = {
  0: 'הנחה על הפריט',
  1: 'הנחה בקנייה מרובה',
  2: 'מחיר מיוחד',
  3: 'הנחה באחוזים',
}

export function describeDiscountType(discountType: number | null): string {
  if (discountType === null) return 'לא צוין'
  return DISCOUNT_TYPES[discountType] ?? `סוג ${discountType}`
}
