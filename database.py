from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import settings

SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://root:{settings.mysql_password}@localhost:3306/url_db"
engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
