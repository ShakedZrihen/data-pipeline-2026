import { Link } from 'react-router-dom'
import type { PriceSummary, Product } from '../api/types'
import { describeProductId, formatDate, formatPrice } from '../lib/format'
import { summarySpread } from '../lib/prices'

interface ProductCardProps {
  product: Product
  /** Opens the price dialog. A real link, so ctrl-click and share still work. */
  to: string
}

export function ProductCard({ product, to }: ProductCardProps) {
  const identity = describeProductId(product.product_id)

  return (
    <li className="card">
      <Link className="card__link" to={to}>
        <h2 className="card__title">{product.display_name ?? 'מוצר ללא שם'}</h2>
      </Link>

      <PriceBlock summary={product.price_summary} />

      <div className="card__chips">
        <span
          className={identity.comparable ? 'chip chip--good' : 'chip chip--neutral'}
          title={identity.hint}
        >
          {identity.label}
        </span>
        {product.gtin && <span className="chip chip--ghost">{product.gtin}</span>}
      </div>

      <dl className="card__meta">
        <div>
          <dt>עודכן</dt>
          <dd>{formatDate(product.updated_at)}</dd>
        </div>
        {product.manufacturer && (
          <div>
            <dt>יצרן</dt>
            <dd>{product.manufacturer}</dd>
          </div>
        )}
      </dl>
    </li>
  )
}

function PriceBlock({ summary }: { summary: PriceSummary | null | undefined }) {
  if (!summary) {
    return (
      <p className="price price--missing">
        אין עדיין מחיר — המוצר בקטלוג אך לא בטבלת המחירים
      </p>
    )
  }

  const spread = summarySpread(summary)

  return (
    <div className="price">
      <div className="price__headline">
        {/* Without "from", a single figure would read as the price everywhere. */}
        {spread && <span className="price__prefix">מ־</span>}
        <strong className="price__amount">{formatPrice(summary.min_price)}</strong>
        {spread && (
          <span className="price__upto">עד {formatPrice(summary.max_price)}</span>
        )}
      </div>

      <p className="price__context">
        {describeCoverage(summary)}
        {spread && <span className="price__spread">פער {spread.percent.toFixed(0)}%</span>}
      </p>
    </div>
  )
}

function describeCoverage({ store_count, chain_count }: PriceSummary): string {
  const stores = store_count === 1 ? 'סניף אחד' : `${store_count} סניפים`
  const chains = chain_count === 1 ? 'רשת אחת' : `${chain_count} רשתות`
  return `${stores} ב־${chains}`
}
