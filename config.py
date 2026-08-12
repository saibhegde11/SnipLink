from pydantic_settings import BaseSettings

class Settings(BaseSettings) : 
    mysql_password : str

    class Config : 
        env_file = ".env"

settings = Settings()