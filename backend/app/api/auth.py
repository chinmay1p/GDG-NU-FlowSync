from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from app.core.security import verify_firebase_token, get_current_user

router = APIRouter(prefix='/auth', tags=['auth'])


class LoginRequest(BaseModel):
	idToken: str


class UserResponse(BaseModel):
	uid: str
	email: str | None = None
	name: str | None = None
	picture: str | None = None


@router.post('/login', response_model=UserResponse)
async def login(request: LoginRequest):
	"""
	Verify Firebase ID token and return user info.
	
	Accepts Firebase ID token from frontend and verifies it.
	Returns user uid, email, name, and picture if token is valid.
	"""
	if not request.idToken:
		raise HTTPException(status_code=401, detail='ID token is required')
 
	claims = verify_firebase_token(request.idToken)
 
	return UserResponse(
	 uid=claims.get('uid'),
	 email=claims.get('email'),
	 name=claims.get('name'),
	 picture=claims.get('picture'),
	)


@router.get('/me', response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
	"""
	Get current authenticated user info from Authorization header.
	
	Protected route that extracts Firebase ID token from Authorization header,
	verifies it, and returns the authenticated user's information.
	"""
	return UserResponse(
	 uid=current_user.get('uid'),
	 email=current_user.get('email'),
	 name=current_user.get('name'),
	 picture=current_user.get('picture'),
	)
