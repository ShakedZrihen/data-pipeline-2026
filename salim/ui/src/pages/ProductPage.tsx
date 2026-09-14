import { Link, useParams } from 'react-router-dom'
import { ProductDetail } from '../components/ProductDetail'

/** Standalone page for a shared /products/<id> link; the catalog uses a dialog. */
export function ProductPage() {
  const { productId = '' } = useParams()

  return (
    <>
      <Link className="back" to="/">
        חזרה לקטלוג
      </Link>
      <ProductDetail productId={productId} />
    </>
  )
}
