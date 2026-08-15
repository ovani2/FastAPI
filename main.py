import os
from fastapi import FastAPI, Depends, Request, Form, UploadFile, File as FastAPIFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from db import get_db, User, File, init_db

app = FastAPI()

app.mount("/css", StaticFiles(directory="templates/css"), name="css")
templates = Jinja2Templates(directory="templates/html")

UPLOAD_DIR = "user_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)

init_db()


# Схеми Pydantic
class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    space: float = 5.0


class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    space: float

    class Config:
        from_attributes = True


# Роути HTML-сторінок
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.get("/index", response_class=HTMLResponse)
async def index_page(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "user": user, 
        "files": user.files
    })


@app.get("/load_file", response_class=HTMLResponse)
async def load_file_page(request: Request, user_id: int):
    return templates.TemplateResponse("load_file.html", {"request": request, "user_id": user_id})


# Обробка HTML-форм
@app.post("/register/")
async def register(
    username: str = Form(...), 
    email: str = Form(...), 
    password: str = Form(...), 
    db: Session = Depends(get_db)
):
    db_user = User(username=username, email=email, password=password)
    db.add(db_user)
    db.commit()
    return RedirectResponse(url="/login", status_code=303)


@app.post("/login/")
async def login(
    email: str = Form(...), 
    password: str = Form(...), 
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == email).first()
    if not user or user.password != password:
        raise HTTPException(status_code=401, detail="Невірний логін або пароль")

    return RedirectResponse(url=f"/index?user_id={user.id}", status_code=303)


@app.post("/load_file/")
async def load_file(
    user_id: int = Form(...), 
    file: UploadFile = FastAPIFile(...), 
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Користувача не знайдено")

    contents = await file.read()
    file_size_gb = len(contents) / (1024 ** 3)

    if user.space < file_size_gb:
        raise HTTPException(status_code=400, detail="Недостатньо місця на диску")

    user_dir = os.path.join(UPLOAD_DIR, str(user.id))
    os.makedirs(user_dir, exist_ok=True)

    file_path = os.path.join(user_dir, file.filename)

    with open(file_path, "wb") as f:
        f.write(contents)

    user.space -= file_size_gb
    db_file = File(
        filename=file.filename,
        filepath=file_path,
        file_size_gb=file_size_gb,
        owner_id=user.id
    )
    db.add(db_file)
    db.commit()

    return RedirectResponse(url=f"/index?user_id={user.id}", status_code=303)


# Скачування та видалення файлів
@app.get("/download_file/{file_id}")
async def download_file(file_id: int, db: Session = Depends(get_db)):
    db_file = db.query(File).filter(File.id == file_id).first()
    if not db_file or not os.path.exists(db_file.filepath):
        raise HTTPException(status_code=404, detail="Файл не знайдено")

    return FileResponse(path=db_file.filepath, filename=db_file.filename)


@app.post("/delete_file/{file_id}")
async def delete_file(file_id: int, user_id: int = Form(...), db: Session = Depends(get_db)):
    db_file = db.query(File).filter(File.id == file_id).first()
    if not db_file:
        raise HTTPException(status_code=404, detail="Файл не знайдено")

    user = db.query(User).filter(User.id == user_id).first()

    if os.path.exists(db_file.filepath):
        os.remove(db_file.filepath)

        user_dir = os.path.dirname(db_file.filepath)
        if os.path.exists(user_dir) and not os.listdir(user_dir):
            os.rmdir(user_dir)

    if user:
        user.space += db_file.file_size_gb

    db.delete(db_file)
    db.commit()

    return RedirectResponse(url=f"/index?user_id={user_id}", status_code=303)