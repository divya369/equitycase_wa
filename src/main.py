from fastapi import FastAPI

from config.app_config import app_config
from config.lifespan import lifespan
from config.logging import configure_logging
from core.rate_limit import limiter
from errors.handlers import register_error_handlers
from middlewares.request_id import request_id_middleware
from routes import register_routes

configure_logging()


app = FastAPI(title=app_config.app_name, lifespan=lifespan)
app.state.limiter = limiter
app.middleware("http")(request_id_middleware)
register_error_handlers(app)
register_routes(app)
