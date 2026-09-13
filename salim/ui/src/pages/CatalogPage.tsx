import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listProducts } from '../api/client'
import { Modal } from '../components/Modal'
import { ProductCard } from '../components/ProductCard'
import { ProductDetail } from '../components/ProductDetail'
import { Status } from '../components/Status'
import { useAsync } from '../hooks/useAsync'
import { useDebounced } from '../hooks/useDebounced'

const PAGE_SIZE = 24

export function CatalogPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const query = searchParams.get('q') ?? ''
  const promoOnly = searchParams.get('promo') === '1'
  const page = Math.max(0, Number(searchParams.get('page')) || 0)

  const [draft, setDraft] = useState(query)
  const debouncedDraft = useDebounced(draft, 350)

  function updateParams(changes: Record<string, string | null>) {
    const next = new URLSearchParams(searchParams)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
    setSearchParams(next, { replace: true })
  }

  // Typing rewrites the URL rather than component state, so a search is
  // shareable and the back button behaves.
  useEffect(() => {
    if (debouncedDraft === query) return
    updateParams({ q: debouncedDraft, page: null })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedDraft])

  // One row beyond the page tells us whether a next page exists; /products
  // returns a bare list with no total.
  const state = useAsync(
    (signal) =>
      listProducts(
        {
          q: query || undefined,
          hasPromotion: promoOnly || undefined,
          limit: PAGE_SIZE + 1,
          offset: page * PAGE_SIZE,
        },
        signal,
      ),
    [query, promoOnly, page],
  )

  const products = state.data?.slice(0, PAGE_SIZE) ?? []
  const hasNext = (state.data?.length ?? 0) > PAGE_SIZE

  // The open dialog lives in the URL, so Back closes it and a link to one
  // product's prices can be shared.
  const selectedId = searchParams.get('product')
  const selected = products.find((product) => product.product_id === selectedId)

  function linkToProduct(productId: string): string {
    const next = new URLSearchParams(searchParams)
    next.set('product', productId)
    return `?${next}`
  }

  return (
    <section>
      <form className="filters" role="search" onSubmit={(event) => event.preventDefault()}>
        <label className="field field--grow">
          <span className="field__label">חיפוש מוצר</span>
          <input
            className="field__input"
            type="search"
            value={draft}
            placeholder="לדוגמה: חלב, קוטג', שוקולד"
            onChange={(event) => setDraft(event.target.value)}
          />
        </label>

        <label className="toggle">
          <input
            type="checkbox"
            checked={promoOnly}
            onChange={(event) => updateParams({ promo: event.target.checked ? '1' : null, page: null })}
          />
          <span>במבצע כרגע בלבד</span>
        </label>
      </form>

      {state.loading && <Status kind="loading" title="טוען מוצרים…" />}

      {state.error && (
        <Status
          kind="error"
          title="לא הצלחנו לטעון את המוצרים"
          detail={state.error.message}
        />
      )}

      {!state.loading && !state.error && products.length === 0 && (
        <Status
          kind="empty"
          title="לא נמצאו מוצרים"
          detail={
            query
              ? `אין מוצר שמכיל "${query}". החיפוש מתבצע על שם המוצר כפי שהרשת פרסמה אותו.`
              : 'טבלת catalog_products ריקה — כנראה שה-loader עוד לא כתב נתונים.'
          }
        />
      )}

      {products.length > 0 && (
        <>
          <ul className="grid">
            {products.map((product) => (
              <ProductCard
                key={product.product_id}
                product={product}
                to={linkToProduct(product.product_id)}
              />
            ))}
          </ul>

          <nav className="pager" aria-label="עימוד">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => updateParams({ page: page > 1 ? String(page - 1) : null })}
            >
              הקודם
            </button>
            <span className="pager__label">עמוד {page + 1}</span>
            <button type="button" disabled={!hasNext} onClick={() => updateParams({ page: String(page + 1) })}>
              הבא
            </button>
          </nav>
        </>
      )}

      {selectedId && (
        <Modal label="מחירי המוצר בכל הסניפים" onClose={() => updateParams({ product: null })}>
          <ProductDetail productId={selectedId} product={selected} />
        </Modal>
      )}
    </section>
  )
}
