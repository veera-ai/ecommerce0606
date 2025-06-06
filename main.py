"""
Main FastAPI application implementing the mock ecommerce API, as specified in openapi.yaml.

All data is kept in process-memory (stateless per run, no persistence), and authentication is just for demonstration.
"""

from fastapi import FastAPI, Query, HTTPException, Path, Request, status, Depends, Response, Header
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, date
import secrets

app = FastAPI(
    title="Mock Ecommerce Sample APIs",
    description="Unified stateless mock API service for ecommerce scenarios with in-memory dummy data.",
    version="1.0.0"
)

# --------
# Dummy data (for demonstration/testing)
# --------

PRODUCTS = [
    {
        "id": f"sku{i:06d}",
        "name": f"Product {i}",
        "description": f"Sample product {i}.",
        "price": float(9.99 + i),
        "image": f"https://example.com/images/p{i}.jpg",
        "category": "cat-a" if i % 2 == 0 else "cat-b",
        "stock": 30 - (i % 15),
        "rating": round(3.5 + (i % 5) * 0.3, 1)
    }
    for i in range(1, 51)
]

PRODUCT_DETAILS = {
    product["id"]: {
        **product,
        "details": f"Full details for {product['name']}",
        "specifications": {
            "color": "Red" if int(product["id"][3:]) % 2 == 0 else "Blue",
            "size": "Standard"
        }
    } for product in PRODUCTS
}

MOCK_USER = {
    "userId": "user_demo",
    "username": "demo",
    "email": "demo@example.com",
    "displayName": "Demo User"
}

VALID_USERNAME = "demo@example.com"
VALID_PASSWORD = "password123"
MOCK_TOKEN = "mockjwttoken123456"  # In real-world, generate JWTs; here it's hardcoded

# Simple in-memory "cart" store
CART: Dict[str, List[Dict[str, Any]]] = {}

# -----------
# Utilities
# -----------

def get_cart_for_token(token: str) -> List[Dict[str, Any]]:
    if token not in CART:
        CART[token] = []
    return CART[token]

def get_token_from_header(authorization: Optional[str]) -> Optional[str]:
    """Extracts the token part from 'Bearer <token>' string."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None

# PUBLIC_INTERFACE
def require_auth(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False))):
    """Dependency for endpoints that require mock authentication."""
    # For demo purposes, compare to the hardcoded token
    if not credentials or credentials.credentials != MOCK_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return credentials.credentials

# -----
# API Endpoints

# Product Listing
# PUBLIC_INTERFACE
@app.get("/products", summary="List products")
async def list_products(
    page: int = Query(1, ge=1, description="Page number for pagination (starts from 1)"),
    pageSize: int = Query(20, ge=1, le=100, description="Number of products per page"),
    category: Optional[str] = Query(None, description="Filter by category identifier"),
    search: Optional[str] = Query(None, description="Full-text product search")
):
    """Returns a paginated list of products with optional category/search filter."""

    filtered = PRODUCTS
    if category:
        filtered = [p for p in filtered if p["category"] == category]
    if search:
        q = search.lower()
        filtered = [p for p in filtered if q in p["name"].lower() or q in p["description"].lower()]
    total = len(filtered)
    totalPages = max(1, (total + pageSize - 1) // pageSize)
    if (page - 1) * pageSize >= total and total > 0:
        raise HTTPException(status_code=400, detail="Invalid pagination parameters.")
    start = (page - 1) * pageSize
    end = start + pageSize
    page_products = filtered[start:end]
    return {
        "products": page_products,
        "page": page,
        "pageSize": pageSize,
        "total": total,
        "totalPages": totalPages
    }

# Product Details
# PUBLIC_INTERFACE
@app.get("/products/{productId}", summary="Get product details")
async def get_product_details(
    productId: str = Path(..., description="Product SKU, e.g., sku123456")
):
    product = PRODUCT_DETAILS.get(productId)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

# Cart - Get
# PUBLIC_INTERFACE
@app.get("/cart", summary="Get cart contents")
async def get_cart(authorization: Optional[str] = Header(None)):
    """Returns the current contents of the user's 'session' cart."""
    token = get_token_from_header(authorization)
    token = token or "anonymous"  # demo: non-authenticated users get "anonymous" cart
    cart_items = get_cart_for_token(token)
    # For each cart item, fill in info from products
    response_items = []
    for item in cart_items:
        product = next((p for p in PRODUCTS if p["id"] == item["productId"]), None)
        if product:
            response_items.append({
                "productId": product["id"],
                "name": product["name"],
                "quantity": item["quantity"],
                "price": product["price"],
                "image": product["image"],
            })
    return {
        "items": response_items,
        "totalPrice": sum(i["price"] * i["quantity"] for i in response_items),
        "totalItems": sum(i["quantity"] for i in response_items)
    }

# Cart - Add/Update
# PUBLIC_INTERFACE
@app.post("/cart", summary="Add or update item in cart")
async def add_update_cart_item(
    body: Dict[str, Any],
    authorization: Optional[str] = Header(None)
):
    productId = body.get("productId")
    quantity = body.get("quantity")
    if not productId or not isinstance(quantity, int) or quantity < 1:
        raise HTTPException(status_code=400, detail="Bad request input")
    # Check product exists
    product = next((p for p in PRODUCTS if p["id"] == productId), None)
    if not product:
        raise HTTPException(status_code=400, detail="Invalid product")
    token = get_token_from_header(authorization)
    token = token or "anonymous"
    cart = get_cart_for_token(token)
    existing = next((item for item in cart if item["productId"] == productId), None)
    if existing:
        existing["quantity"] = quantity
    else:
        cart.append({"productId": productId, "quantity": quantity})
    # Return cart state
    return await get_cart(authorization)

# Cart - Remove Item
# PUBLIC_INTERFACE
@app.delete("/cart/{productId}", summary="Remove item from cart")
async def remove_cart_item(
    productId: str = Path(..., description="Product SKU"),
    authorization: Optional[str] = Header(None)
):
    token = get_token_from_header(authorization)
    token = token or "anonymous"
    cart = get_cart_for_token(token)
    idx = next((i for i, item in enumerate(cart) if item["productId"] == productId), -1)
    if idx < 0:
        raise HTTPException(status_code=404, detail="Product not found in cart")
    cart.pop(idx)
    return await get_cart(authorization)

# Order Simulation
# PUBLIC_INTERFACE
@app.post("/order/simulate", summary="Simulate order placement")
async def simulate_order(
    body: Dict[str, Any],
    authorization: Optional[str] = Header(None)
):
    for field in ["customerName", "address", "email"]:
        if not body.get(field):
            raise HTTPException(status_code=400, detail="Invalid input data")
    token = get_token_from_header(authorization)
    token = token or "anonymous"
    cart_items = get_cart_for_token(token)
    response_items = []
    for item in cart_items:
        product = next((p for p in PRODUCTS if p["id"] == item["productId"]), None)
        if product:
            response_items.append({
                "productId": product["id"],
                "name": product["name"],
                "quantity": item["quantity"],
                "price": product["price"],
                "image": product["image"],
            })
    order_id = f"order{str(secrets.randbelow(10**8)).zfill(8)}"
    return {
        "orderId": order_id,
        "status": "success" if cart_items else "failed",
        "estimatedDelivery": (date.today() + timedelta(days=7)).isoformat(),
        "total": sum(i["price"] * i["quantity"] for i in response_items),
        "items": response_items
    }

# Mock Authentication: Login
# PUBLIC_INTERFACE
@app.post("/auth/login", summary="Mock user login")
async def login(body: Dict[str, Any]):
    username = body.get("username")
    password = body.get("password")
    if username == VALID_USERNAME and password == VALID_PASSWORD:
        return {
            "token": MOCK_TOKEN,
            "expiresIn": 60 * 60  # 1 hour (for demo)
        }
    raise HTTPException(status_code=401, detail="Unauthorized - bad credentials")

# Mock Authentication: Get profile
# PUBLIC_INTERFACE
@app.get("/auth/me", summary="Get current mock user profile")
async def get_me(token: str = Depends(require_auth)):
    return MOCK_USER

# -----------
# Exception handling for OpenAPI "message" schema
# -----------

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, str):
        return JSONResponse(
            status_code=exc.status_code,
            content={"message": exc.detail}
        )
    return await app.default_exception_handler(request, exc)

# -----------
# Serve OpenAPI spec file directly (optional, for reference)
# -----------
from fastapi.staticfiles import StaticFiles
import os

openapi_path = os.path.abspath("openapi.yaml")
if os.path.exists(openapi_path):
    app.mount("/spec", StaticFiles(directory=os.path.dirname(openapi_path)), name="spec")
