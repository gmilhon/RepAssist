"""Canned, deterministic scenario data so demos feel real and repeatable.

Each 'existing agent' keys its behaviour off the order/account id, so you can
drive specific outcomes from the chat UI:

  ACT-1001  activation  -> auto-fixable (re-provision)
  ACT-1002  activation  -> not fixable -> human ticket
  ORD-2002  pending     -> auto-fixable (expedite blocking order ORD-1990)
  ORD-2003  pending     -> not fixable (credit hold) -> human ticket
  AC-3003   promo       -> auto-fixable (re-apply BOGO)
  AC-3004   promo       -> resolved with no action (customer ineligible)
"""

ORDERS = {
    "ACT-1001": {"order_id": "ACT-1001", "type": "New Activation", "status": "Activation Pending",
                 "device": "iPhone 17 Pro", "line": "(555) 010-1001", "account_id": "AC-3001"},
    "ACT-1002": {"order_id": "ACT-1002", "type": "New Activation", "status": "Carrier Port Pending",
                 "device": "Pixel 10", "line": "(555) 010-1002", "account_id": "AC-3002"},
    "ORD-2002": {"order_id": "ORD-2002", "type": "Upgrade", "status": "Blocked",
                 "device": "Galaxy S26", "line": "(555) 010-2002", "account_id": "AC-3003"},
    "ORD-2003": {"order_id": "ORD-2003", "type": "New Line", "status": "Blocked",
                 "device": "iPhone 17", "line": "(555) 010-2003", "account_id": "AC-3010"},
}

ACCOUNTS = {
    "AC-3003": {"account_id": "AC-3003", "name": "J. Rivera", "plan": "Unlimited Ultimate",
                "lines": 3, "tenure_months": 41},
    "AC-3004": {"account_id": "AC-3004", "name": "M. Okafor", "plan": "Unlimited Welcome",
                "lines": 1, "tenure_months": 2},
    # OCC scenarios
    "AC-5001": {"account_id": "AC-5001", "name": "K. Patel", "plan": "Unlimited Plus",
                "lines": 2, "tenure_months": 1},
    "AC-5002": {"account_id": "AC-5002", "name": "D. Thompson", "plan": "Unlimited Ultimate",
                "lines": 4, "tenure_months": 18},
    "AC-5003": {"account_id": "AC-5003", "name": "L. Chen", "plan": "Unlimited Welcome",
                "lines": 1, "tenure_months": 8},
}

KB_ARTICLES = [
    {"keywords": ["bill", "charge", "prorate", "proration", "invoice"],
     "article_id": "KB-1042",
     "answer": "First-month charges are prorated from the activation date plus one "
               "full month billed in advance, which is why the first bill looks high. "
               "It normalizes on the second cycle."},
    {"keywords": ["upgrade", "eligible", "eligibility", "device payment"],
     "article_id": "KB-2071",
     "answer": "A line is upgrade-eligible once the device payment agreement is 50% "
               "paid or after the trade-in window opens. Check the Device tab for the "
               "'Upgrade eligible' badge."},
]
