import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import { listStores } from './api/client'
import { useAsync } from './hooks/useAsync'
import { CatalogPage } from './pages/CatalogPage'
import { ProductPage } from './pages/ProductPage'

function ChainBar() {
  // /stores lists chains, not branches — the endpoint name is historical.
  const state = useAsync((signal) => listStores(signal), [])
  const chains = state.data?.items ?? []

  if (chains.length === 0) return null

  return (
    <div className="chainbar">
      <span className="chainbar__label">רשתות במערכת</span>
      <ul className="chainbar__list">
        {chains.map((chain) => (
          <li key={chain.chain_id} className="chip chip--ghost" title={`ChainId ${chain.chain_id}`}>
            {chain.name}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="shell">
        <header className="masthead">
          <Link to="/" className="masthead__brand">
            <span className="masthead__mark">₪</span>
            <span>
              <strong>Salim</strong>
              <small>קטלוג מחירי הסופרמרקטים</small>
            </span>
          </Link>
          <ChainBar />
        </header>

        <main className="content">
          <Routes>
            <Route path="/" element={<CatalogPage />} />
            <Route path="/products/:productId" element={<ProductPage />} />
            <Route path="*" element={<CatalogPage />} />
          </Routes>
        </main>

        <footer className="footer">
          נתונים מתוך פרסומי שקיפות המחירים של הרשתות, דרך הפייפליין של <code>salim</code>
        </footer>
      </div>
    </BrowserRouter>
  )
}
