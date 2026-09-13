import { getProduct, getProductPrices, getProductPromotions } from '../api/client'
import type { Product } from '../api/types'
import { useAsync } from '../hooks/useAsync'
import { describeProductId, formatDateTime, formatPrice } from '../lib/format'
import { mergePriceRows, priceSpread } from '../lib/prices'
import { PriceTable } from './PriceTable'
import { PromotionList } from './PromotionList'
import { Status } from './Status'

// MAX_PRICE_LIMIT in api/repository.py. Asking for both ends at the cap means
// the two lists overlap entirely for any product in 50 stores or fewer.
const PRICE_LIMIT = 50

interface ProductDetailProps {
  productId: string
  /** Passed straight from the catalog, which already knows the price span. */
  product?: Product
}

export function ProductDetail({ productId, product: known }: ProductDetailProps) {
  const fetched = useAsync(
    (signal) => (known ? Promise.resolve(known) : getProduct(productId, signal)),
    [productId, known],
  )
  const prices = useAsync(
    (signal) =>
      Promise.all([
        getProductPrices(productId, 'lowest', PRICE_LIMIT, signal),
        getProductPrices(productId, 'highest', PRICE_LIMIT, signal),
      ]),
    [productId],
  )
  const promotions = useAsync((signal) => getProductPromotions(productId, true, signal), [productId])

  const product = known ?? fetched.data
  if (fetched.loading && !product) return <Status kind="loading" title="טוען מוצר…" />
  if (!product) {
    return <Status kind="error" title="המוצר לא נמצא" detail={fetched.error?.message} />
  }

  const identity = describeProductId(product.product_id)
  const rows = prices.data ? mergePriceRows(prices.data[0], prices.data[1]) : []
  const spread = prices.data ? priceSpread(prices.data[0], prices.data[1]) : null
  const total = product.price_summary?.store_count
  const truncated = total !== undefined && total > rows.length

  return (
    <article className="detail">
      <header className="detail__header">
        <h2 className="detail__title">{product.display_name ?? 'מוצר ללא שם'}</h2>
        <div className="card__chips">
          <span
            className={identity.comparable ? 'chip chip--good' : 'chip chip--neutral'}
            title={identity.hint}
          >
            {identity.label}
          </span>
          {product.gtin && <span className="chip chip--ghost">ברקוד {product.gtin}</span>}
        </div>
        <p className="detail__hint">{identity.hint}</p>
      </header>

      {spread && (
        <section className="spread">
          <div className="spread__figure">
            <span className="spread__label">הזול ביותר</span>
            <strong className="spread__value spread__value--low">{formatPrice(spread.min)}</strong>
          </div>
          <div className="spread__figure">
            <span className="spread__label">היקר ביותר</span>
            <strong className="spread__value spread__value--high">{formatPrice(spread.max)}</strong>
          </div>
          <div className="spread__figure">
            <span className="spread__label">חוסכים עד</span>
            <strong className="spread__value">
              {formatPrice(spread.diff)} ({spread.percent.toFixed(0)}%)
            </strong>
          </div>
        </section>
      )}

      <section className="panel">
        <h3>המחיר בכל סניף, מהזול ליקר</h3>

        {prices.loading && <Status kind="loading" title="טוען מחירים…" />}
        {prices.error && (
          <Status kind="error" title="טעינת המחירים נכשלה" detail={prices.error.message} />
        )}
        {!prices.loading && !prices.error && rows.length === 0 && (
          <Status
            kind="empty"
            title="אין מחירים למוצר הזה"
            detail="המוצר קיים בקטלוג אבל אין לו שורה בטבלת prices."
          />
        )}

        {rows.length > 0 && (
          <>
            <PriceTable prices={rows} />
            {truncated && (
              <p className="detail__note">
                המוצר נמכר ב־{total} סניפים. מוצגים {PRICE_LIMIT} הזולים ו־{PRICE_LIMIT} היקרים,
                כך שהקצוות כאן והאמצע חסר.
              </p>
            )}
          </>
        )}
      </section>

      <section className="panel">
        <h3>מבצעים פעילים</h3>
        {promotions.loading && <Status kind="loading" title="טוען מבצעים…" />}
        {promotions.error && (
          <Status kind="error" title="טעינת המבצעים נכשלה" detail={promotions.error.message} />
        )}
        {promotions.data && !promotions.data.has_promotion && (
          <Status kind="empty" title="אין מבצע פעיל על המוצר הזה כרגע" />
        )}
        {promotions.data?.has_promotion && <PromotionList promotions={promotions.data.promotions} />}
      </section>

      <footer className="detail__footer">
        <code>{product.product_id}</code>
        <span>עודכן במסד הנתונים: {formatDateTime(product.updated_at)}</span>
      </footer>
    </article>
  )
}
