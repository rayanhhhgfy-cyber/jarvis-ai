# ====================================================================
# JARVIS OMEGA - E-commerce Plugin (Phase 11)
# ====================================================================
"""
Products, orders, inventory, invoices, shipping tracking.

Tools:
  ecommerce.add_product / list_products / update_inventory
  ecommerce.create_order / list_orders / update_order_status
  ecommerce.lookup_tracking   - public USPS/UPS/FedEx tracking pages
  ecommerce.generate_packing_slip
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from backend.tools import tool, RiskTier
from backend import business_db
from backend.config import settings


# --------------------------------------------------------------------
# Products
# --------------------------------------------------------------------

@tool(
    name="ecommerce.add_product",
    description="Add a product to the catalog.",
    parameters={
        "type": "object",
        "properties": {
            "client_id": {"type": "integer", "default": 0},
            "name": {"type": "string"},
            "sku": {"type": "string", "default": "", "description": "Auto-generated UUID if empty."},
            "price": {"type": "number"},
            "currency": {"type": "string", "default": "USD"},
            "inventory": {"type": "integer", "default": 0},
            "description": {"type": "string", "default": ""},
            "image_url": {"type": "string", "default": ""},
        },
        "required": ["name", "price"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="ecommerce",
)
async def ecommerce_add_product(
    name: str, price: float, sku: str = "", currency: str = "USD",
    inventory: int = 0, description: str = "", image_url: str = "",
    client_id: int = 0,
) -> Dict[str, Any]:
    final_sku = sku or f"SKU-{uuid.uuid4().hex[:8].upper()}"
    try:
        pid = business_db.execute(
            """INSERT INTO products (client_id, name, sku, price, currency, inventory,
                                     description, image_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (client_id or None, name, final_sku, price, currency, inventory,
             description, image_url, datetime.utcnow().isoformat()),
        )
    except Exception as e:
        return {"ok": False, "error": f"duplicate SKU? {e}"}
    return {"ok": True, "product_id": pid, "sku": final_sku}


@tool(
    name="ecommerce.list_products",
    description="List products. Filter by active state.",
    parameters={
        "type": "object",
        "properties": {
            "active_only": {"type": "boolean", "default": True},
            "limit": {"type": "integer", "default": 100},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="ecommerce",
)
async def ecommerce_list_products(active_only: bool = True, limit: int = 100) -> Dict[str, Any]:
    sql = "SELECT * FROM products"
    params: tuple = ()
    if active_only:
        sql += " WHERE active = 1"
    sql += " LIMIT ?"
    params = (limit,)
    rows = business_db.rows_to_dicts(business_db.query(sql, params))
    return {"ok": True, "count": len(rows), "products": rows}


@tool(
    name="ecommerce.update_inventory",
    description="Adjust inventory for a product by SKU.",
    parameters={
        "type": "object",
        "properties": {
            "sku": {"type": "string"},
            "delta": {"type": "integer", "description": "Positive adds, negative removes."},
            "set_exact": {"type": "integer", "default": -1, "description": "If >= 0, set inventory to this value (overrides delta)."},
        },
        "required": ["sku", "delta"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="ecommerce",
)
async def ecommerce_update_inventory(sku: str, delta: int, set_exact: int = -1) -> Dict[str, Any]:
    if set_exact >= 0:
        business_db.execute(
            "UPDATE products SET inventory = ? WHERE sku = ?",
            (set_exact, sku),
        )
    else:
        business_db.execute(
            "UPDATE products SET inventory = inventory + ? WHERE sku = ?",
            (delta, sku),
        )
    row = business_db.query_one("SELECT sku, inventory FROM products WHERE sku = ?", (sku,))
    return {"ok": True, "product": dict(row) if row else None}


# --------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------

@tool(
    name="ecommerce.create_order",
    description="Create a new order. Looks up product price by SKU and decrements inventory.",
    parameters={
        "type": "object",
        "properties": {
            "client_id": {"type": "integer", "default": 0},
            "customer_name": {"type": "string"},
            "customer_email": {"type": "string", "default": ""},
            "customer_address": {"type": "string", "default": ""},
            "sku": {"type": "string"},
            "quantity": {"type": "integer", "default": 1},
            "notes": {"type": "string", "default": ""},
        },
        "required": ["customer_name", "sku"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="ecommerce",
)
async def ecommerce_create_order(
    customer_name: str, sku: str, quantity: int = 1,
    client_id: int = 0, customer_email: str = "",
    customer_address: str = "", notes: str = "",
) -> Dict[str, Any]:
    prod = business_db.query_one("SELECT * FROM products WHERE sku = ?", (sku,))
    if not prod:
        return {"ok": False, "error": f"unknown SKU: {sku}"}
    if prod["inventory"] < quantity:
        return {"ok": False, "error": f"insufficient inventory ({prod['inventory']} < {quantity})"}

    unit_price = prod["price"]
    total = unit_price * quantity
    currency = prod["currency"]
    oid = business_db.execute(
        """INSERT INTO orders (client_id, customer_name, customer_email, customer_address,
                               product_id, quantity, unit_price, total, currency,
                               status, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
        (client_id or None, customer_name, customer_email, customer_address,
         prod["id"], quantity, unit_price, total, currency,
         notes, datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
    )
    # Decrement inventory.
    business_db.execute(
        "UPDATE products SET inventory = inventory - ? WHERE id = ?",
        (quantity, prod["id"]),
    )
    business_db.audit("create_order", "ecommerce", target=str(oid),
                      details={"sku": sku, "qty": quantity, "total": total})
    return {
        "ok": True, "order_id": oid, "total": total, "currency": currency,
        "unit_price": unit_price, "quantity": quantity,
    }


@tool(
    name="ecommerce.list_orders",
    description="List orders. Filter by status.",
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "default": ""},
            "limit": {"type": "integer", "default": 50},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="ecommerce",
)
async def ecommerce_list_orders(status: str = "", limit: int = 50) -> Dict[str, Any]:
    sql = "SELECT * FROM orders"
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY id DESC LIMIT ?"
    params = params + (limit,)
    rows = business_db.rows_to_dicts(business_db.query(sql, params))
    return {"ok": True, "count": len(rows), "orders": rows}


@tool(
    name="ecommerce.update_order_status",
    description="Update an order's status (and optionally set tracking).",
    parameters={
        "type": "object",
        "properties": {
            "order_id": {"type": "integer"},
            "status": {"type": "string", "enum": ["pending", "paid", "fulfilled", "shipped", "delivered", "refunded"]},
            "tracking_number": {"type": "string", "default": ""},
            "carrier": {"type": "string", "default": ""},
        },
        "required": ["order_id", "status"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="ecommerce",
)
async def ecommerce_update_order_status(
    order_id: int, status: str, tracking_number: str = "", carrier: str = "",
) -> Dict[str, Any]:
    if tracking_number:
        business_db.execute(
            "UPDATE orders SET status = ?, tracking_number = ?, carrier = ?, updated_at = ? WHERE id = ?",
            (status, tracking_number, carrier, datetime.utcnow().isoformat(), order_id),
        )
    else:
        business_db.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.utcnow().isoformat(), order_id),
        )
    return {"ok": True, "order_id": order_id, "status": status}


# --------------------------------------------------------------------
# Tracking (public carrier pages)
# --------------------------------------------------------------------

@tool(
    name="ecommerce.lookup_tracking",
    description="Get the public tracking URL for a tracking number. Auto-detects carrier by format.",
    parameters={
        "type": "object",
        "properties": {
            "tracking_number": {"type": "string"},
            "carrier": {"type": "string", "default": "", "description": "Force a carrier: usps, ups, fedex, dhl. Empty = auto-detect."},
        },
        "required": ["tracking_number"],
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="ecommerce",
)
async def ecommerce_lookup_tracking(tracking_number: str, carrier: str = "") -> Dict[str, Any]:
    tn = tracking_number.strip()
    if not carrier:
        if tn.startswith(("9400", "9405", "9270", "9505", "94")):
            carrier = "usps"
        elif tn.startswith("1Z"):
            carrier = "ups"
        elif tn.startswith(("612", "748", "403", "588", "627", "638")):
            carrier = "fedex"
        elif len(tn) == 10 and tn.isdigit():
            carrier = "dhl"
        else:
            carrier = "unknown"
    urls = {
        "usps": f"https://tools.usps.com/go/TrackConfirmAction?tLabels={tn}",
        "ups": f"https://www.ups.com/track?tracknum={tn}",
        "fedex": f"https://www.fedex.com/fedextrack/?tracknumbers={tn}",
        "dhl": f"https://www.dhl.com/us-en/home/tracking/tracking-parcel.html?submit=1&tracking-id={tn}",
    }
    return {
        "ok": True,
        "tracking_number": tn,
        "carrier": carrier,
        "url": urls.get(carrier, ""),
    }


# --------------------------------------------------------------------
# Packing slip
# --------------------------------------------------------------------

@tool(
    name="ecommerce.generate_packing_slip",
    description="Generate a printable HTML packing slip for an order.",
    parameters={
        "type": "object",
        "properties": {
            "order_id": {"type": "integer"},
            "output_dir": {"type": "string", "default": "./storage/sales/packing_slips"},
        },
        "required": ["order_id"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="ecommerce",
)
async def ecommerce_generate_packing_slip(order_id: int, output_dir: str = "./storage/sales/packing_slips") -> Dict[str, Any]:
    order = business_db.query_one("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not order:
        return {"ok": False, "error": f"order not found: {order_id}"}
    prod = business_db.query_one("SELECT * FROM products WHERE id = ?", (order["product_id"],))
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = out_dir / f"packing_slip_order_{order_id}.html"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Packing Slip #{order_id}</title>
<style>
body {{ font-family: Arial, sans-serif; padding: 40px; }}
h1 {{ font-size: 24px; }}
.row {{ margin: 4px 0; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
td, th {{ border: 1px solid #ccc; padding: 8px; }}
</style></head><body>
<h1>Packing Slip</h1>
<div class="row"><strong>Order #:</strong> {order_id}</div>
<div class="row"><strong>Date:</strong> {order['created_at']}</div>
<div class="row"><strong>Customer:</strong> {order['customer_name']}</div>
<div class="row"><strong>Email:</strong> {order['customer_email'] or '-'}</div>
<div class="row"><strong>Address:</strong> {order['customer_address'] or '-'}</div>
<table>
<tr><th>Item</th><th>SKU</th><th>Qty</th><th>Price</th><th>Total</th></tr>
<tr>
  <td>{prod['name'] if prod else '?'}</td>
  <td>{prod['sku'] if prod else '?'}</td>
  <td>{order['quantity']}</td>
  <td>{order['unit_price']} {order['currency']}</td>
  <td>{order['total']} {order['currency']}</td>
</tr>
</table>
<p>Thank you for your order!</p>
</body></html>"""
    fname.write_text(html, encoding="utf-8")
    return {"ok": True, "path": str(fname)}


PLUGIN_NAME = "ecommerce"
PLUGIN_VERSION = "1.1.0"
PLUGIN_DESCRIPTION = (
    "Products, orders, inventory, packing slips, shipment tracking, "
    "customer email notifications, public order-tracking HTML page."
)


# --------------------------------------------------------------------
# Phase 12: customer notifications
# --------------------------------------------------------------------

@tool(
    name="ecommerce.notify_customer",
    description="Send a transactional email to an order's customer (order confirmation, shipping update, etc.). Persists in notifications table.",
    parameters={
        "type": "object",
        "properties": {
            "order_id": {"type": "integer"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
        },
        "required": ["order_id", "subject", "body"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="ecommerce",
)
async def ecommerce_notify_customer(
    order_id: int, subject: str, body: str, language: str = "ar",
) -> Dict[str, Any]:
    order = business_db.query_one("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not order:
        return {"ok": False, "error": f"order not found: {order_id}"}
    if not order["customer_email"]:
        # Still record the notification attempt.
        nid = business_db.execute(
            """INSERT INTO notifications (order_id, channel, recipient, subject, body, status, error, created_at)
               VALUES (?, 'email', '', ?, ?, 'failed', 'no customer email on order', ?)""",
            (order_id, subject, body, datetime.utcnow().isoformat()),
        )
        return {"ok": False, "error": "order has no customer_email", "notification_id": nid}

    from plugins.communication.plugin import email_send
    result = await email_send(to=order["customer_email"], subject=subject, body=body)
    status = "sent" if result.get("ok") else "failed"
    err = result.get("error", "")
    nid = business_db.execute(
        """INSERT INTO notifications (order_id, channel, recipient, subject, body, status, error, sent_at, created_at)
           VALUES (?, 'email', ?, ?, ?, ?, ?, ?, ?)""",
        (order_id, order["customer_email"], subject, body,
         status, err,
         datetime.utcnow().isoformat() if status == "sent" else None,
         datetime.utcnow().isoformat()),
    )
    return {"ok": result.get("ok", False), "notification_id": nid, "send_result": result}


@tool(
    name="ecommerce.order_status_update_with_notify",
    description="Update an order's status AND email the customer automatically. Templates are bilingual (Arabic default).",
    parameters={
        "type": "object",
        "properties": {
            "order_id": {"type": "integer"},
            "status": {"type": "string", "enum": ["pending", "paid", "fulfilled", "shipped", "delivered", "refunded"]},
            "tracking_number": {"type": "string", "default": ""},
            "carrier": {"type": "string", "default": ""},
            "language": {"type": "string", "default": "ar", "enum": ["ar", "en"]},
        },
        "required": ["order_id", "status"],
    },
    risk_tier=RiskTier.TIER_4_EXTERNAL,
    category="ecommerce",
)
async def ecommerce_order_status_update_with_notify(
    order_id: int, status: str, tracking_number: str = "", carrier: str = "",
    language: str = "ar",
) -> Dict[str, Any]:
    # 1. Update the order
    upd = await ecommerce_update_order_status(
        order_id=order_id, status=status,
        tracking_number=tracking_number, carrier=carrier,
    )
    if not upd.get("ok"):
        return upd

    order = business_db.query_one("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not order:
        return {"ok": True, "updated": True, "notified": False, "reason": "order vanished"}

    # 2. Pick a localized template.
    templates_ar = {
        "paid": ("تأكيد الطلب", f"طلبك رقم #{order_id} تم تأكيده ودفع قيمته. شكراً لثقتك بنا!"),
        "fulfilled": ("طلبك قيد التجهيز", f"طلبك رقم #{order_id} قيد التجهيز وسيتم شحنه قريباً."),
        "shipped": ("تم شحن طلبك", f"تم شحن طلبك رقم #{order_id}. رقم التتبع: {tracking_number or 'غير متوفر'} via {carrier or 'شركة الشحن'}."),
        "delivered": ("تم توصيل طلبك", f"تم توصيل طلبك رقم #{order_id}. نأمل أن تكون راضياً — شاركنا رأيك!"),
        "refunded": ("تم استرداد المبلغ", f"تم استرداد مبلغ طلبك رقم #{order_id}. قد يستغرق الظهور في حسابك 3-5 أيام عمل."),
    }
    templates_en = {
        "paid": ("Order confirmed", f"Your order #{order_id} has been confirmed and paid. Thank you!"),
        "fulfilled": ("Order in preparation", f"Your order #{order_id} is being prepared and will ship soon."),
        "shipped": ("Your order has shipped", f"Order #{order_id} shipped. Tracking: {tracking_number or 'N/A'} via {carrier or 'carrier'}."),
        "delivered": ("Your order was delivered", f"Order #{order_id} was delivered. We hope you love it — please share feedback!"),
        "refunded": ("Refund processed", f"Refund for order #{order_id} has been processed. Allow 3-5 business days to appear."),
    }
    tpl = (templates_ar if language == "ar" else templates_en).get(status)
    if not tpl:
        return {"ok": True, "updated": True, "notified": False, "reason": "no template for status"}

    notify = await ecommerce_notify_customer(
        order_id=order_id, subject=tpl[0], body=tpl[1], language=language,
    )
    return {"ok": True, "updated": True, "notified": notify.get("ok", False), "notification": notify}


@tool(
    name="ecommerce.generate_tracking_page",
    description="Generate a standalone public HTML order-tracking page for a customer. Arabic-first, RTL.",
    parameters={
        "type": "object",
        "properties": {
            "order_id": {"type": "integer"},
            "output_dir": {"type": "string", "default": "./storage/website/tracking"},
        },
        "required": ["order_id"],
    },
    risk_tier=RiskTier.TIER_1_REVERSIBLE,
    category="ecommerce",
)
async def ecommerce_generate_tracking_page(
    order_id: int, output_dir: str = "./storage/website/tracking",
) -> Dict[str, Any]:
    order = business_db.query_one("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not order:
        return {"ok": False, "error": f"order not found: {order_id}"}

    # Tracking URL if carrier known.
    tracking_url = ""
    if order["tracking_number"]:
        lookup = await ecommerce_lookup_tracking(
            tracking_number=order["tracking_number"], carrier=order["carrier"] or "",
        )
        if lookup.get("ok"):
            tracking_url = lookup.get("url", "")

    status_ar = {
        "pending": "قيد الانتظار", "paid": "تم الدفع", "fulfilled": "قيد التجهيز",
        "shipped": "تم الشحن", "delivered": "تم التوصيل", "refunded": "مسترجع",
    }.get(order["status"], order["status"])

    html = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>تتبع الطلب #{order_id}</title>
<link rel="stylesheet" href="https://cdn.tailwindcss.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap">
<style>body{{font-family:"Tajawal",Arial,sans-serif;background:#f3f4f6;padding:40px}}</style>
</head>
<body>
<div class="max-w-2xl mx-auto bg-white rounded-lg shadow p-8">
  <h1 class="text-3xl font-bold mb-4">تتبع الطلب #{order_id}</h1>
  <div class="space-y-3 text-lg">
    <p><strong>العميل:</strong> {order['customer_name']}</p>
    <p><strong>التاريخ:</strong> {order['created_at']}</p>
    <p><strong>الحالة:</strong> <span class="inline-block px-3 py-1 rounded bg-indigo-100 text-indigo-800">{status_ar}</span></p>
    {'<p><strong>رقم الشحن:</strong> ' + order['tracking_number'] + '</p>' if order['tracking_number'] else ''}
    {'<p><strong>الشركة:</strong> ' + order['carrier'] + '</p>' if order['carrier'] else ''}
    {'<p><strong>الإجمالي:</strong> ' + str(order['total']) + ' ' + order['currency'] + '</p>'}
  </div>
  {f'<a href="{tracking_url}" target="_blank" class="mt-6 inline-block bg-indigo-600 text-white px-6 py-3 rounded-lg">تتبع الشحنة مباشرة →</a>' if tracking_url else ''}
  <p class="mt-6 text-gray-500 text-sm">هذه الصفحة مُولّدة تلقائياً بواسطة JARVIS OMEGA.</p>
</div>
</body>
</html>"""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = out_dir / f"order_{order_id}.html"
    fname.write_text(html, encoding="utf-8")
    return {"ok": True, "path": str(fname), "order_id": order_id, "tracking_url": tracking_url}


@tool(
    name="ecommerce.list_notifications",
    description="List customer notifications for an order (or all orders).",
    parameters={
        "type": "object",
        "properties": {
            "order_id": {"type": "integer", "default": 0, "description": "Empty/0 = all orders."},
            "limit": {"type": "integer", "default": 50},
        },
    },
    risk_tier=RiskTier.TIER_0_OBSERVE,
    category="ecommerce",
)
async def ecommerce_list_notifications(order_id: int = 0, limit: int = 50) -> Dict[str, Any]:
    sql = "SELECT * FROM notifications"
    params: tuple = ()
    if order_id:
        sql += " WHERE order_id = ?"
        params = (order_id,)
    sql += " ORDER BY id DESC LIMIT ?"
    params = params + (limit,)
    rows = business_db.rows_to_dicts(business_db.query(sql, params))
    return {"ok": True, "count": len(rows), "notifications": rows}
