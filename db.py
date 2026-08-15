import enum
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Enum, ForeignKey, Table
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship


SQLALCHEMY_DATABASE_URL = "postgresql+psycopg2://postgres:admin@localhost:5432/messenger_db"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String)
    space = Column(Integer, default=5)



def init_db():
    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


