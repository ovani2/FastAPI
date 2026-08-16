import os
from dotenv import load_dotenv
import random
import shutil
import uuid
from typing import Optional

from fastapi import FastAPI, Depends, Request, Form, UploadFile, File as FastAPIFile, HTTPException, status, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import jwt, JWTError
import resend

from db import get_db, User, File, init_db

load_dotenv()

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY не знайдено в .env файлі")

resend.api_key = RESEND_API_KEY

app = FastAPI()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app.mount("/css", StaticFiles(directory="templates/css"), name="css")
templates = Jinja2Templates(directory="templates/html")

UPLOAD_DIR = "user_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)

init_db()


# Хелпери для паролів та токенів
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict) -> str:
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(access_token: Optional[str] = Cookie(None), db: Session = Depends(get_db)) -> User:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неавторизований")
    try:
        payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
        raw_id = payload.get("sub")
        if raw_id is None:
            raise HTTPException(status_code=401, detail="Невалідний токен")
        user_id = int(raw_id)
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="Невалідний токен")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Користувача не знайдено")
    return user


# HTML-сторінки (Виправлено синтаксис TemplateResponse)
@app.get("/", response_class=HTMLResponse)
async def read_root():
    return RedirectResponse(url="/login", status_code=303)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html")

@app.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request, email: str):
    return templates.TemplateResponse(request, "verify.html", {"email": email})

@app.get("/index", response_class=HTMLResponse)
async def index_page(
    request: Request, 
    user: User = Depends(get_current_user)
):
    return templates.TemplateResponse(request, "index.html", {
        "user": user, 
        "files": user.files
    })

@app.get("/load_file", response_class=HTMLResponse)
async def load_file_page(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(request, "load_file.html", {"user": user})


# API Роути
@app.post("/register/")
async def register(
    username: str = Form(...), 
    email: str = Form(...), 
    password: str = Form(...),
    db: Session = Depends(get_db)
):  
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Користувач з таким email вже існує")

    verification_code = "".join(random.sample("0123456789", 5))

    try:
        resend.Emails.send({
            "from": "onboarding@resend.dev",
            "to": email,
            "subject": "Код підтвердження реєстрації",
            "html": f"<p>Ваш код підтвердження: <b>{verification_code}</b></p>"
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Помилка відправки листа: {str(e)}")

    hashed_pw = get_password_hash(password)
    
    db_user = User(
        username=username, 
        email=email, 
        password=hashed_pw,
        verification_code=verification_code,
        is_active=False
    )
    db.add(db_user)
    db.commit()

    return RedirectResponse(url=f"/verify?email={email}", status_code=303)


@app.post("/verify/")
async def verify_code(
    email: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")

    if user.verification_code != code:
        raise HTTPException(status_code=400, detail="Невірний код підтвердження")

    user.is_active = True
    user.verification_code = None
    db.commit()

    return RedirectResponse(url="/login", status_code=303)


@app.post("/login/")
async def login(
    email: str = Form(...), 
    password: str = Form(...), 
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password):
        raise HTTPException(status_code=401, detail="Невірний логін або пароль")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Акаунт не підтверджено. Перевірте пошту.")

    token = create_access_token({"sub": str(user.id)})
    
    response = RedirectResponse(url="/index", status_code=303)
    response.set_cookie(key="access_token", value=token, httponly=True)
    return response


@app.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("access_token")
    return response


@app.post("/load_file/")
async def load_file(
    file: UploadFile = FastAPIFile(...), 
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user_dir = os.path.join(UPLOAD_DIR, str(user.id))
    os.makedirs(user_dir, exist_ok=True)

    uqi = uuid.uuid4()
    _, ext = os.path.splitext(file.filename or "")
    file_path = os.path.join(user_dir, f"{uqi}{ext}")

    max_allowed_bytes = user.space * (1024 ** 3)
    file_size_bytes = 0

    try:
        with open(file_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):  
                file_size_bytes += len(chunk)

                if file_size_bytes > max_allowed_bytes:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Перевищено доступний дисковий простір ({user.space:.2f} GB)"
                    )

                buffer.write(chunk)

    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise e

    file_size_gb = file_size_bytes / (1024 ** 3)

    user.space -= file_size_gb
    db_file = File(
        filename=file.filename,
        filepath=file_path,
        file_size_gb=file_size_gb,
        owner_id=user.id
    )
    db.add(db_file)
    db.commit()

    return RedirectResponse(url="/index", status_code=303)


@app.get("/download_file/{file_id}")
async def download_file(
    file_id: int, 
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_file = db.query(File).filter(File.id == file_id, File.owner_id == user.id).first()
    
    if not db_file or not os.path.exists(db_file.filepath):
        raise HTTPException(status_code=404, detail="Файл не знайдено або немає доступу")

    return FileResponse(path=db_file.filepath, filename=db_file.filename)


@app.post("/delete_file/{file_id}")
async def delete_file(
    file_id: int, 
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_file = db.query(File).filter(
        File.id == file_id, 
        File.owner_id == user.id
    ).first()

    if not db_file:
        raise HTTPException(
            status_code=404, 
            detail="Файл не знайдено або у вас немає прав на його видалення"
        )

    if os.path.exists(db_file.filepath):
        os.remove(db_file.filepath)

        user_dir = os.path.dirname(db_file.filepath)
        if os.path.exists(user_dir) and not os.listdir(user_dir):
            os.rmdir(user_dir)

    user.space += db_file.file_size_gb

    db.delete(db_file)
    db.commit()

    return RedirectResponse(url="/index", status_code=303)