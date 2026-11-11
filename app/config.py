"""
Réglages de l'API, lus dans les variables d'environnement.
"""
import logging
import os
import secrets

logger = logging.getLogger("evaluations_api")

JWT_ALGORITHM = "HS256"
TOKEN_TTL_MINUTES = int(os.environ.get("API_TOKEN_TTL_MINUTES", "60"))

JWT_SECRET = os.environ.get("API_JWT_SECRET")
if not JWT_SECRET:
    # Secret aléatoire : correct en développement, mais les jetons ne survivent pas
    # à un redémarrage et ne sont pas partagés entre plusieurs processus
    JWT_SECRET = secrets.token_urlsafe(32)
    logger.warning("API_JWT_SECRET non défini : secret aléatoire généré pour ce processus")

# Origines autorisées pour un futur front (ex. "http://localhost:3000,https://rh.exemple.fr")
CORS_ORIGINS = [o.strip() for o in os.environ.get("API_CORS_ORIGINS", "").split(",") if o.strip()]
