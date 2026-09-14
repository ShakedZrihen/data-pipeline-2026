# Salim UI

A React + TypeScript front end over the `api` service: search the product
catalog, then see where each product is cheapest and which promotions cover it.

## Running against a local API

```bash
cd salim/ui
npm install
npm run dev              # http://localhost:5173
```

The dev server proxies `/api` to `http://localhost:8000` (override with
`API_TARGET`), so the browser only ever talks to one origin and CORS never
comes up. The API itself has to be running:

```bash
cd salim
docker compose up api          # or: DATABASE_URL=... uvicorn api.main:app
```

## Running the whole stack

```bash
cd salim
docker compose up --build ui
```

nginx serves the build on `http://localhost:3000` (`UI_PORT`) and proxies
`/api` to the `api` service.

## Deploying the UI separately from the API

Two origins means the browser needs an explicit CORS grant:

1. Build with `VITE_API_BASE_URL` set to the API's public URL. Vite inlines
   `VITE_*` at build time, so this is a build argument, not a runtime one.
2. Add the UI's origin to the API's `UI_ORIGINS` (comma-separated; it defaults
   to the Vite dev and preview ports).

## What the screens show

**Catalog** (`/`) — text search over `catalog_products.display_name`, an
"on promotion now" filter, and paging. Each card carries the span of the
product's current prices, from `/products`, so the grid needs no request per
card. The search term and page live in the URL, so a result is shareable.

**Product prices** — clicking a card opens a dialog listing the price in every
branch, cheapest first, with the extremes tagged. It is driven by `?product=`
on the catalog URL, so Back closes it and a link to one product's prices can be
shared. `/products/:productId` renders the same content as a standalone page,
for a link shared from before.

Two details worth knowing:

- The API exposes only the N cheapest and N priciest prices, never a plain
  list, so the dialog asks for both at the 50-row cap and stitches them
  together. Products in 50 branches or fewer come back complete; beyond that
  the middle is missing and the dialog says so.
- Ties are the norm — a chain usually charges one price across its branches —
  so the "cheapest"/"priciest" tags mark every row matching the extreme price,
  not just the first one in the list.

## Things the data itself imposes

- **Only barcode products compare across chains.** `product_id` is
  `gtin:<barcode>` for a real barcode (`item_type` 1) and
  `chain:<chainId>:<itemCode>` for a code one chain invented for itself. The
  second kind can never have a competitor's price beside it, so each product is
  badged accordingly rather than leaving the user to wonder why a product shows
  one chain.
- **Prices name a branch, not a place.** A price row carries a bare `store_id`,
  and only `/stores/{chain_id}` can name it — it returns every branch of that
  chain at once. `src/api/branches.ts` fetches each chain once per session and
  fills the names in after the prices render. Chains with no rows in `branches`
  (Victory, Tiv Ta'am, Super-Pharm, as of now) fall back to the raw id.
- **Branch ids are not padded consistently across a chain's own files.**
  Shufersal's Stores file publishes `1`..`98` while its price files say `001`,
  so all 415 of its branches resolved to nothing. `canonicalId` in
  `src/api/branches.ts` drops leading zeros on both sides, preferring an exact
  match first so a chain that really distinguishes `1` from `001` is unharmed.
  This is a workaround: the fix belongs in the stores service, which should
  persist one canonical form. Hatzi Hinam still does not resolve, but for a
  different reason — its price files reference store `103` while its current
  Stores file lists `201`..`219`.
- **`catalog_products.manufacturer` is never written** by the loader —
  manufacturer enrichment lands on `products.manufacturer`, per chain SKU. So
  there is no manufacturer filter here, and the field only renders when present.
- **`catalog_products.slug` is likewise always null**, so search effectively
  matches display names only.
- **`/products` returns a bare list with no total**, so paging asks for one row
  beyond the page to learn whether a next page exists, and shows no total count.
