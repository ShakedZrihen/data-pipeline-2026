# FastAPI read API over the prices and stores data.
# Expected env vars: DATABASE_URL, UI_ORIGINS

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from api import repository as repo
from api.deps import get_session
from api.schemas import (
    PriceOut,
    ProductListItemOut,
    ProductOut,
    ProductPromotionsOut,
    StoreDetailOut,
    StoreListOut,
)

DEFAULT_UI_ORIGINS = "http://localhost:5173,http://localhost:4173"

app = FastAPI(title="Salim Price API")

# The UI runs on its own origin, so without these response headers the browser
# fetches successfully and then refuses to hand the body to JavaScript.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("UI_ORIGINS", DEFAULT_UI_ORIGINS).split(",") if o.strip()],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/stores", response_model=StoreListOut)
def list_stores(
    chain_id: str | None = None,
    slug: str | None = None,
    name: str | None = None,
    city: str | None = None,
    branch_name: Annotated[str | None, Query(alias="branchName")] = None,
    is_active: Annotated[bool | None, Query(alias="isActive")] = None,
    limit: int = Query(repo.DEFAULT_STORE_LIMIT, ge=1, le=repo.MAX_STORE_LIMIT),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    return repo.list_stores(
        session,
        chain_id=chain_id,
        slug=slug,
        name=name,
        city=city,
        branch_name=branch_name,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/stores/{store_id}",
    response_model=StoreDetailOut,
    responses={404: {"description": "Store not found"}},
)
def get_store(store_id: str, session: Session = Depends(get_session)):
    store = repo.get_store(session, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail=f"Store '{store_id}' not found")
    return store


@app.get("/products", response_model=list[ProductListItemOut])
def list_products(
    q: str | None = Query(None, description="Search product name or slug"),
    manufacturer: str | None = Query(None, description="Exact manufacturer match (case-insensitive)"),
    has_promotion: bool | None = Query(None, description="Only products currently on promotion (true) or not (false)"),
    limit: int = Query(repo.DEFAULT_LIST_LIMIT, ge=1, le=repo.MAX_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """Catalog products, each with the span of its current prices."""
    products = repo.list_products(
        session, q=q, manufacturer=manufacturer, has_promotion=has_promotion, limit=limit, offset=offset
    )
    summaries = repo.price_summary(session, [product.product_id for product in products])
    return [
        ProductListItemOut(
            **ProductOut.model_validate(product).model_dump(),
            price_summary=summaries.get(product.product_id),
        )
        for product in products
    ]


@app.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: str, session: Session = Depends(get_session)):
    product = repo.get_product(session, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    return product


@app.get("/products/{product_id}/prices/lowest", response_model=list[PriceOut])
def product_lowest_prices(
    product_id: str,
    limit: int = Query(repo.DEFAULT_PRICE_LIMIT, ge=1, le=repo.MAX_PRICE_LIMIT),
    session: Session = Depends(get_session),
):
    """The N cheapest current prices for this product, across every chain and store."""
    _require_product(session, product_id)
    return repo.product_prices(session, product_id, order="asc", limit=limit)


@app.get("/products/{product_id}/prices/highest", response_model=list[PriceOut])
def product_highest_prices(
    product_id: str,
    limit: int = Query(repo.DEFAULT_PRICE_LIMIT, ge=1, le=repo.MAX_PRICE_LIMIT),
    session: Session = Depends(get_session),
):
    """The N priciest current prices for this product, across every chain and store."""
    _require_product(session, product_id)
    return repo.product_prices(session, product_id, order="desc", limit=limit)


@app.get("/products/{product_id}/promotions", response_model=ProductPromotionsOut)
def product_promotions(
    product_id: str,
    active_only: bool = Query(True, description="Only currently active promotions"),
    session: Session = Depends(get_session),
):
    """Whether this product currently has a promotion, and the promotions themselves."""
    _require_product(session, product_id)
    promotions = repo.product_promotions(session, product_id, active_only=active_only)
    return {"has_promotion": len(promotions) > 0, "promotions": promotions}


def _require_product(session: Session, product_id: str) -> None:
    if repo.get_product(session, product_id) is None:
        raise HTTPException(status_code=404, detail="product not found")
