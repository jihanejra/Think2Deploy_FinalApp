"""
Authentification par jeton JWT (OAuth2 « password flow ») et contrôle du profil.

Comptes de démonstration (mot de passe « 123 »), hachés en PBKDF2-SHA256 avec sel.
En production : un annuaire (LDAP, SSO) ou une table d'utilisateurs.
"""
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app import config

PBKDF2_ITERATIONS = 200_000

# username: (nom, profil, sel, hachage)
USERS = {
    "rh_user": ("Responsable RH", "RH", "5b7389a6c6965a5b86f8f9ad8c57cfbe",
                "ccfbca4026528302765deadb7504a776fed3fd318de57ffb9e5856e1ed940878"),
    "user.cdi": ("Salarié CDI", "CDI", "5f6574e869c80d0f2ba45ab9dc7a8a73",
                 "f3858fd0692da2df90349bc3ffa68932892584694fd1e8e7062f6f0180202de7"),
    "user.cdd": ("Salarié CDD", "CDD", "e95529d3554860eb5780b9901d22e7ea",
                 "37d79c9574e85931bfb7ff8d102c53fd4595cd17208124187fbc0874cfaac302"),
    "user.stagiaire": ("Stagiaire", "Stagiaire", "466465664d238a5007004693053f7d8e",
                       "89aa1d1f8556ab2d6b112680f0a7f440e7dc6de36d21c5cdb468ca92fc94e067"),
    "user.interim": ("Intérimaire", "Intérim", "fde71925faafe1991a67ad9abc0cf39a",
                     "07eb64f4e487ccdd40d6dd6d964133e190be9c885d869528d574661bcd289b80"),
    "user.cadre": ("Cadre", "Cadre", "f4d0fca0bbb0dfa74a2d20c58f8ea93b",
                   "191758acfa43484f1dcc18541f1c55a60a8a141ebc28b902bd9a33f2c687b965"),
    "user.noncadre": ("Non-cadre", "Non-cadre", "9b3519b99fc772f4ea83ed010827043f",
                      "9ddea6ac52c1d92d1d8147bef60e0447dc18e9925fd11a8b4629034debd8c737"),
    "user.apprenti": ("Apprenti", "Apprenti", "f8e83022a572928554687ee91b230d68",
                      "cf980492cfc9abb6a218b74423712fbcbab84c5cc25cefb568b5560bed35d5ee"),
}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


@dataclass
class User:
    username: str
    name: str
    profil: str


def _hash_password(password, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex),
                               PBKDF2_ITERATIONS).hex()


def authenticate(username, password):
    record = USERS.get(username)
    if record is None:
        # Même coût de calcul qu'un compte existant : ne révèle pas quels comptes existent
        _hash_password(password, "00" * 16)
        return None
    name, profil, salt, expected = record
    if not hmac.compare_digest(_hash_password(password, salt), expected):
        return None
    return User(username, name, profil)


def create_access_token(user):
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=config.TOKEN_TTL_MINUTES)
    token = jwt.encode({"sub": user.username, "profil": user.profil, "exp": expires_at},
                       config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)
    return token, expires_at


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Jeton invalide ou expiré",
                                 headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise unauthorized
    record = USERS.get(payload.get("sub"))
    if record is None:
        raise unauthorized
    return User(payload["sub"], record[0], record[1])


def require_rh(user: User = Depends(get_current_user)) -> User:
    """Les analyses des évaluations sont réservées au profil RH"""
    if user.profil != "RH":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Accès réservé au profil RH")
    return user
