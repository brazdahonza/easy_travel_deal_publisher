import logging
from typing import Dict, Tuple

log = logging.getLogger(__name__)


def generate_patreon_post(deal: Dict, brand_name: str = "flynow.cz") -> Tuple[str, str]:
    """
    Generate Patreon post title and body text.
    
    Args:
        deal: Deal dictionary with keys like destination, departure_city, price, etc.
        brand_name: Brand name for attribution
    
    Returns:
        Tuple of (title, body_text)
    """
    destination = deal.get('destination', 'Neznámá destinace')
    departure_city = deal.get('departure_city', 'Praha')
    price = deal.get('price', '?')
    discount = deal.get('discount_pct', 0)
    date_from = deal.get('date_from', '')
    date_to = deal.get('date_to', '')
    ticket_url = deal.get('ticket_url', '')
    
    title = f"{destination} z {departure_city} za {price} Kč"
    
    # Format dates if available
    dates_str = ""
    if date_from and date_to:
        dates_str = f"Léty: {date_from} - {date_to}\n"
    
    # Format discount if available
    discount_str = ""
    if discount:
        discount_str = f"Sleva: {discount}%\n"
    
    body = f"🎉 Skvělá nabídka od {brand_name}!\n\n"
    body += f"Destinace: {destination}\n"
    body += f"Odlet z: {departure_city}\n"
    body += f"Cena: {price} Kč\n"
    body += dates_str
    body += discount_str
    
    if ticket_url:
        body += f"\nZískejte letenku: {ticket_url}"
    
    return (title, body)


def generate_twitter_post(deal: Dict, brand_tag: str = "#flynowcz") -> str:
    text = f"{deal.get('destination')} z {deal.get('departure_city')} — {deal.get('price')} Kč {brand_tag} {deal.get('ticket_url','') }"
    return text[:280]
