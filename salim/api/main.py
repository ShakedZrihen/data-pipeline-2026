# FastAPI read API over the prices data.
# Expected env var: DATABASE_URL

from fastapi import FastAPI

app = FastAPI(
    title="Salim Price API",
    description="API for accessing supermarket prices, products and stores.",
    version="1.0.0",
)


@app.get(
    "/health",
    tags=["Health"],
    summary="Check API health",
    description="Returns the current health status of the Salim Price API.",
    response_description="API health status",
)
def health():
    return {"status": "ok"}


# TODO: GET /stores, GET /products/{id}, GET /prices endpoints
# (see shared/models.py for the underlying tables and api/schemas.py for response shapes)
