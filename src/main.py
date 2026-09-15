from fastapi import FastAPI



app = FastAPI()


@app.get("/helthz")
def helthz():
    return {"status":"helthy"}