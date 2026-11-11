from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.schemas import Token, UserOut
from app.security import User, authenticate, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["Authentification"])


@router.post("/token", response_model=Token, summary="Obtenir un jeton d'accès")
def login(form: OAuth2PasswordRequestForm = Depends()):
    user = authenticate(form.username, form.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiants incorrects",
                            headers={"WWW-Authenticate": "Bearer"})
    token, expires_at = create_access_token(user)
    return Token(access_token=token, expires_at=expires_at)


@router.get("/me", response_model=UserOut, summary="Utilisateur connecté")
def me(user: User = Depends(get_current_user)):
    return UserOut(username=user.username, name=user.name, profil=user.profil)
