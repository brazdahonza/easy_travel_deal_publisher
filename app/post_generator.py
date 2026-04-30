import logging
from typing import Dict, Tuple

log = logging.getLogger(__name__)


def generate_patreon_post(deal: Dict, brand_name: str = "flynow.cz") -> Tuple[str, str]:
    destination = deal.get('destination', 'Neznámá destinace')
    departure_city = deal.get('departure_city', 'Praha')
    price = deal.get('price', '?')
    discount = deal.get('discount_pct', 0)
    date_from = deal.get('date_from', '')
    date_to = deal.get('date_to', '')
    ticket_url = deal.get('ticket_url', '')

    log.info("📝 Generating Patreon post — %s from %s at %s CZK", destination, departure_city, price)

    title = f"{destination} z {departure_city} za {price} Kč"

    dates_str = ""
    if date_from and date_to:
        dates_str = f"Léty: {date_from} - {date_to}\n"
        log.debug("  📅 Dates: %s → %s", date_from, date_to)

    discount_str = ""
    if discount:
        discount_str = f"Sleva: {discount}%\n"
        log.debug("  💸 Discount: %.1f%%", discount)

    body = f"🎉 Skvělá nabídka od {brand_name}!\n\n"
    body += f"Destinace: {destination}\n"
    body += f"Odlet z: {departure_city}\n"
    body += f"Cena: {price} Kč\n"
    body += dates_str
    body += discount_str

    if ticket_url:
        body += f"\nZískejte letenku: {ticket_url}"
        log.debug("  🔗 Ticket URL attached")
    else:
        log.debug("  ⚠️  No ticket URL provided")

    log.info("✅ Patreon post ready — title='%s' body_len=%d chars", title, len(body))
    return (title, body)


def generate_twitter_post(deal: Dict, brand_tag: str = "#flynowcz") -> str:
    destination = deal.get('destination')
    departure_city = deal.get('departure_city')
    price = deal.get('price')
    ticket_url = deal.get('ticket_url', '')

    log.info("🐦 Generating Twitter post — %s from %s at %s CZK", destination, departure_city, price)

    text = f"{destination} z {departure_city} — {price} Kč {brand_tag} {ticket_url}"
    text = text[:280]

    log.info("✅ Twitter post ready — %d chars", len(text))
    return text
