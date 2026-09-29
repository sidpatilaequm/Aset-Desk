"""Claude API calls: invoice reading and reply suggestions. Optional — needs ANTHROPIC_API_KEY."""
import base64, json, re
from fastapi import HTTPException
from .config import settings

CATEGORIES = ["Laptop", "Desktop", "Monitor", "Mobile phone", "Server", "Network equipment", "Printer / scanner",
              "Office equipment", "Furniture", "Vehicle", "Software license", "Other"]

INVOICE_PROMPT = f"""The attached file is a purchase invoice for a company's fixed-asset register. Read it carefully and extract the data.
Reply with ONLY one JSON object, no other text, in this shape:
{{"vendor":string,"vendor_tax_id":string,"invoice_number":string,"invoice_date":"YYYY-MM-DD","currency":"ISO 4217 code","subtotal":number,"tax_total":number,"total":number,
 "items":[{{"description":string,"quantity":number,"unit_price":number,"line_total":number,"category":string,"is_capital_asset":boolean,"serial_numbers":[string]}}],
 "notes":string}}
Rules: numbers are plain numbers without currency symbols or thousands separators. unit_price excludes tax. category must be exactly one of: {", ".join(CATEGORIES)}.
is_capital_asset is false for delivery, installation, services, warranties and consumables. List serial numbers only if printed on the invoice.
Use "" or 0 for anything missing. In notes, briefly mention anything unreadable or inconsistent; otherwise "".
If the file is not an invoice, return {{"items":[],"notes":"This doesn't look like an invoice."}}."""


def _client():
    if not settings.ai_enabled:
        raise HTTPException(503, "Claude isn't configured on the server (ANTHROPIC_API_KEY).")
    import anthropic
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _text(resp) -> str:
    return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")


def _parse_json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except ValueError:
            pass
    a, b = text.find("{"), text.rfind("}")
    if a >= 0 and b > a:
        return json.loads(text[a:b + 1])
    raise ValueError("no JSON in reply")


def read_invoice(data: bytes, content_type: str) -> dict:
    b64 = base64.standard_b64encode(data).decode()
    if content_type == "application/pdf":
        block = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    elif content_type in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        block = {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": b64}}
    else:
        raise HTTPException(400, "Use a JPG, PNG, WebP or PDF invoice.")
    try:
        resp = _client().messages.create(model=settings.anthropic_model, max_tokens=4000,
                                         messages=[{"role": "user", "content": [block, {"type": "text", "text": INVOICE_PROMPT}]}])
        result = _parse_json(_text(resp))
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(502, "The invoice couldn't be turned into line items. Try a clearer image.")
    except Exception as e:  # network / API errors
        raise HTTPException(502, f"Invoice reading failed: {e.__class__.__name__}")
    items = result.get("items") if isinstance(result, dict) else None
    if not isinstance(items, list):
        raise HTTPException(502, "The invoice couldn't be turned into line items. Try a clearer image.")
    for it in items:
        if it.get("category") not in CATEGORIES:
            it["category"] = "Other"
    return result


def draft_reply(prompt: str) -> str:
    try:
        resp = _client().messages.create(model=settings.anthropic_model, max_tokens=800,
                                         messages=[{"role": "user", "content": prompt}])
        return _text(resp).strip()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Couldn't draft a reply: {e.__class__.__name__}")
