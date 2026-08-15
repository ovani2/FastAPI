from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from fastapi.responses import RedirectResponse
from database import engine, get_db, User, Skill, Exchange, Review, CategoryEnum, LevelEnum, StatusEnum

app = FastAPI()



class User(BaseModel):
    id: int
    username: str
    email: EmailStr
    password: str
    space: int | 5

    class Config:
        orm_mode = True



@app.get("/")
async def root():
    return RedirectResponse(url="/login")


@app.get("/login/")
async def login(password: int, email: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.password != password:
        raise HTTPException(status_code=401, detail="Incorrect password")

    return {"message": "Login successful"}, RedirectResponse(url="/index")
 



@app.post("/register/")
async def register(user: User, db: Session = Depends(get_db)):
    db_user = User(username=user.username, email=user.email, password=user.password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user, RedirectResponse(url="/login")


@app.get("/load_file/")
async def load_file()






