import uvicorn
from decouple import config
from src.app import app

if __name__ == "__main__":
    host: str = str(config("HOST", default="0.0.0.0"))
    port: int = config("PORT", default=8000)
    uvicorn.run(app, host=host, port=port)
