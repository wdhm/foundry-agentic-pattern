"""Order Sync: moves confirmed webshop orders to Fabrikam ERP (fictional sample).

Trigger: a message on the Service Bus queue configured in ``config/settings.json``.
Output: one sales order created in Fabrikam ERP through its REST API.
Failure: after the last retry the message goes to the dead-letter queue.
"""

import json
import time
import urllib.request
from pathlib import Path

SETTINGS = json.loads((Path(__file__).parent.parent / "config" / "settings.json").read_text())


def map_order(order: dict) -> dict:
    """Map a webshop OrderConfirmed event to a Fabrikam ERP sales order."""
    return {
        "customerNumber": order["customer"]["id"],
        "externalReference": order["orderId"],
        "currency": order.get("currency", SETTINGS["mapping"]["defaultCurrency"]),
        "lines": [
            {"itemNumber": line["sku"], "quantity": line["qty"], "unitPrice": line["price"]}
            for line in order["lines"]
        ],
    }


def send_to_erp(sales_order: dict) -> None:
    """POST the sales order to Fabrikam ERP, retrying with exponential backoff."""
    erp = SETTINGS["erp"]
    retry = SETTINGS["retry"]
    request = urllib.request.Request(
        url=f"{erp['baseUrl']}{erp['salesOrderPath']}",
        data=json.dumps(sales_order).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(1, retry["maxAttempts"] + 1):
        try:
            urllib.request.urlopen(request, timeout=erp["timeoutSeconds"])
            return
        except OSError:
            if attempt == retry["maxAttempts"]:
                raise
            time.sleep(retry["initialDelaySeconds"] * 2 ** (attempt - 1))


def dead_letter(body: str, reason: str) -> None:
    """Forward a failed message to the dead-letter queue (stubbed in the sample)."""
    print(f"dead-letter -> {SETTINGS['source']['deadLetterQueue']}: {reason}")


def handle_message(body: str) -> None:
    """Entry point for one queue message."""
    try:
        send_to_erp(map_order(json.loads(body)))
    except OSError as error:
        dead_letter(body, str(error))
