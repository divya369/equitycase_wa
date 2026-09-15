from fastapi import FastAPI

from config.app_config import app_config


app = FastAPI(
    title=app_config.app_name,
)


@app.get("/healthz")
def healthz():
    return {"status":"healthy"}