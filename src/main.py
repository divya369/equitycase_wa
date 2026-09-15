from fastapi import FastAPI
from config.app_config import app_config
from config.lifespan import lifespan
from config.logging import configure_logging




configure_logging()



app = FastAPI(
    title=app_config.app_name,
    lifespan=lifespan
)


@app.get("/healthz")
def healthz():
    return {"status":"healthy"}