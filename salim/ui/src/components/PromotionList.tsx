import type { Promotion } from '../api/types'
import { describeDiscountType, formatDateTime, formatPrice, formatQuantity } from '../lib/format'

export function PromotionList({ promotions }: { promotions: Promotion[] }) {
  return (
    <ul className="promotions">
      {promotions.map((promotion) => (
        <li className="promotion" key={`${promotion.provider}:${promotion.store_id}:${promotion.promotion_id}`}>
          <header className="promotion__header">
            <span className="chip">{promotion.chain_name ?? promotion.provider}</span>
            <h3 className="promotion__title">{promotion.description ?? 'מבצע ללא תיאור'}</h3>
          </header>

          <p className="promotion__window">
            בתוקף {formatDateTime(promotion.start_time)} – {formatDateTime(promotion.end_time)}
          </p>

          <table className="table table--compact">
            <thead>
              <tr>
                <th scope="col">פריט</th>
                <th scope="col">סוג ההנחה</th>
                <th scope="col">כמות</th>
                <th scope="col">מחיר במבצע</th>
              </tr>
            </thead>
            <tbody>
              {promotion.items.map((item) => (
                <tr key={item.item_code}>
                  <td className="cell--name">{item.item_name ?? item.item_code}</td>
                  <td>{describeDiscountType(item.discount_type)}</td>
                  <td>{describeQuantity(item.min_qty, item.max_qty)}</td>
                  <td className="cell--price">{formatPrice(item.discount_price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </li>
      ))}
    </ul>
  )
}

function describeQuantity(minQty: Promotion['items'][number]['min_qty'], maxQty: Promotion['items'][number]['max_qty']) {
  const min = formatQuantity(minQty)
  const max = formatQuantity(maxQty)
  if (min === '—' && max === '—') return '—'
  if (max === '—') return `מ-${min}`
  if (min === '—') return `עד ${max}`
  return min === max ? min : `${min}–${max}`
}
