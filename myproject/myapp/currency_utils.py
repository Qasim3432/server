# myapp/currency_utils.py

from decimal import Decimal, ROUND_HALF_UP


def format_dollar(cents):
    if cents is None:
        return "$0.00"
    try:
        dollars = int(cents) / 100.0
        return f"${dollars:,.2f}"
    except (ValueError, TypeError):
        return "$0.00"


def format_local_currency(local_amount, currency_code):
    if local_amount is None:
        local_amount = 0.0
        
    if currency_code == "INR":
        return f"₹{local_amount:,.2f}"
    elif currency_code == "PKR":
        return f"₨{local_amount:,.2f}"
    elif currency_code == "USDT":
        return f"{local_amount:,.2f} USDT"
    return f"{currency_code} {local_amount:,.2f}"


def convert_local_to_cents(local_amount, exchange_rate):
    if exchange_rate <= 0:
        return 0
    usd_value = Decimal(str(local_amount)) / Decimal(str(exchange_rate))
    cents = int((usd_value * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return cents


def convert_cents_to_local(cents, exchange_rate):
    if exchange_rate <= 0:
        return Decimal("0.00")
    
    # ✅ FIX: 100.0 (float) ki jagah Decimal('100') use kiya gaya hai
    usd_value = Decimal(str(cents)) / Decimal('100')
    
    local_value = usd_value * Decimal(str(exchange_rate))
    
    # Return as Decimal (Django models easily accept this)
    return local_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)