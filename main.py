from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from database import engine, get_db, User, Skill, Exchange, Review, CategoryEnum, LevelEnum, StatusEnum

app = FastAPI()

