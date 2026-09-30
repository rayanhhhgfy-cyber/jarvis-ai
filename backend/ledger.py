# ====================================================================
# JARVIS OMEGA — Financial Ledger (Double-Entry Single Source of Truth)
# ====================================================================
"""
Financial Ledger implementation. Serves as the single canonical source
of truth for all money flowing into or out of JARVIS OMEGA businesses.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.business_db import execute, query, query_one, rows_to_dicts
from shared.logger import get_logger

log = get_logger("ledger")


class FinancialLedger:
    """
    Canonical Financial Ledger. Tracks credits (income) and debits (expenses)
    per business or across the entire portfolio.
    """

    def record_entry(
        self,
        entry_type: str,  # 'credit' | 'debit'
        amount: float,
        category: str,
        currency: str = "USD",
        business_id: Optional[int] = None,
        source_event: str = "",
        reference_id: str = "",
        details: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None,
    ) -> int:
        """
        Record a credit or debit entry in the ledger.
        """
        if entry_type not in ("credit", "debit"):
            raise ValueError(f"Invalid entry_type: {entry_type}. Must be 'credit' or 'debit'.")

        ts = timestamp or datetime.utcnow().isoformat()
        details_json = json.dumps(details or {})

        entry_id = execute(
            """
            INSERT INTO ledger_entries (
                entry_type, amount, currency, business_id, category,
                source_event, reference_id, details, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_type,
                float(amount),
                currency.upper(),
                business_id,
                category,
                source_event,
                str(reference_id),
                details_json,
                ts,
            ),
        )
        log.info(
            "ledger_entry_recorded",
            entry_id=entry_id,
            entry_type=entry_type,
            amount=amount,
            category=category,
            business_id=business_id,
        )
        return entry_id

    def get_business_balance(self, business_id: int) -> Dict[str, Any]:
        """
        Get total credits, debits, and net balance for a specific business.
        """
        credit_row = query_one(
            "SELECT COALESCE(SUM(amount), 0) as total FROM ledger_entries WHERE business_id = ? AND entry_type = 'credit'",
            (business_id,),
        )
        debit_row = query_one(
            "SELECT COALESCE(SUM(amount), 0) as total FROM ledger_entries WHERE business_id = ? AND entry_type = 'debit'",
            (business_id,),
        )

        total_credits = float(credit_row["total"]) if credit_row else 0.0
        total_debits = float(debit_row["total"]) if debit_row else 0.0
        net_balance = total_credits - total_debits

        return {
            "business_id": business_id,
            "total_credits": total_credits,
            "total_debits": total_debits,
            "net_balance": net_balance,
        }

    def get_portfolio_balance(self) -> Dict[str, Any]:
        """
        Get total credits, debits, and net balance across the entire portfolio.
        """
        credit_row = query_one(
            "SELECT COALESCE(SUM(amount), 0) as total FROM ledger_entries WHERE entry_type = 'credit'"
        )
        debit_row = query_one(
            "SELECT COALESCE(SUM(amount), 0) as total FROM ledger_entries WHERE entry_type = 'debit'"
        )

        total_credits = float(credit_row["total"]) if credit_row else 0.0
        total_debits = float(debit_row["total"]) if debit_row else 0.0
        net_balance = total_credits - total_debits

        return {
            "total_credits": total_credits,
            "total_debits": total_debits,
            "net_balance": net_balance,
        }

    def get_spend_by_category(self, business_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get total spend (debits) grouped by category.
        """
        if business_id is not None:
            rows = query(
                """
                SELECT category, SUM(amount) as total_spend
                FROM ledger_entries
                WHERE entry_type = 'debit' AND business_id = ?
                GROUP BY category
                ORDER BY total_spend DESC
                """,
                (business_id,),
            )
        else:
            rows = query(
                """
                SELECT category, SUM(amount) as total_spend
                FROM ledger_entries
                WHERE entry_type = 'debit'
                GROUP BY category
                ORDER BY total_spend DESC
                """
            )
        return [{"category": r["category"], "total_spend": float(r["total_spend"])} for r in rows]

    def get_spend_over_time(
        self,
        start_time: str,
        end_time: str,
        business_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all debits within a specific ISO timestamp time range.
        """
        if business_id is not None:
            rows = query(
                """
                SELECT * FROM ledger_entries
                WHERE entry_type = 'debit'
                  AND business_id = ?
                  AND timestamp >= ?
                  AND timestamp <= ?
                ORDER BY timestamp ASC
                """,
                (business_id, start_time, end_time),
            )
        else:
            rows = query(
                """
                SELECT * FROM ledger_entries
                WHERE entry_type = 'debit'
                  AND timestamp >= ?
                  AND timestamp <= ?
                ORDER BY timestamp ASC
                """,
                (start_time, end_time),
            )
        return rows_to_dicts(rows)

    def reconcile_on_first_run(self) -> Dict[str, Any]:
        """
        Reconcile existing historical financial data from `orders`, `invoices`,
        and `audit_log` into the ledger if not already reconciled.
        """
        # Check if reconciliation has already run
        existing_reconcile = query_one(
            "SELECT COUNT(*) as count FROM ledger_entries WHERE source_event = 'audit_log_reconcile' OR source_event = 'orders_reconcile'"
        )
        if existing_reconcile and existing_reconcile["count"] > 0:
            return {"reconciled": False, "reason": "Already reconciled", "entries_added": 0}

        reconciled_count = 0

        # 1. Reconcile paid orders
        paid_orders = query("SELECT * FROM orders WHERE status in ('paid', 'fulfilled', 'delivered')")
        for order in paid_orders:
            o_dict = dict(order)
            self.record_entry(
                entry_type="credit",
                amount=float(o_dict.get("total") or 0.0),
                currency=o_dict.get("currency") or "USD",
                business_id=o_dict.get("client_id"),
                category="stripe_payment",
                source_event="orders_reconcile",
                reference_id=str(o_dict.get("id")),
                details=o_dict,
                timestamp=o_dict.get("created_at"),
            )
            reconciled_count += 1

        # 2. Reconcile paid invoices
        paid_invoices = query("SELECT * FROM invoices WHERE status = 'paid'")
        for inv in paid_invoices:
            inv_dict = dict(inv)
            self.record_entry(
                entry_type="credit",
                amount=float(inv_dict.get("amount") or 0.0),
                currency=inv_dict.get("currency") or "USD",
                business_id=inv_dict.get("client_id"),
                category="invoice_payment",
                source_event="invoices_reconcile",
                reference_id=str(inv_dict.get("id")),
                details=inv_dict,
                timestamp=inv_dict.get("paid_at") or inv_dict.get("created_at"),
            )
            reconciled_count += 1

        # 3. Reconcile audit_log entries containing financial payments or spend
        audit_rows = query("SELECT * FROM audit_log WHERE category IN ('payments', 'marketing', 'payouts')")
        for log_row in audit_rows:
            l_dict = dict(log_row)
            try:
                dt_details = json.loads(l_dict.get("details") or "{}") if isinstance(l_dict.get("details"), str) else (l_dict.get("details") or {})
            except Exception:
                dt_details = {}

            amount = float(dt_details.get("amount") or dt_details.get("amount_usd") or dt_details.get("cost") or 0.0)
            if amount > 0:
                action = l_dict.get("action", "")
                entry_type = "credit" if "payment" in action or "charge" in action or "revenue" in action else "debit"
                self.record_entry(
                    entry_type=entry_type,
                    amount=amount,
                    currency=dt_details.get("currency") or "USD",
                    business_id=dt_details.get("business_id"),
                    category=l_dict.get("category") or "other",
                    source_event="audit_log_reconcile",
                    reference_id=str(l_dict.get("id")),
                    details=dt_details,
                    timestamp=l_dict.get("timestamp"),
                )
                reconciled_count += 1

        return {"reconciled": True, "entries_added": reconciled_count}


ledger = FinancialLedger()
