from typing import Literal

import psycopg
from fastapi import FastAPI, HTTPException, Response

from eval.storage import connect_database, load_gold, load_report

app = FastAPI(title="Signals evaluation API")


@app.get("/api/results")
def get_results(response: Response, split: Literal["dev", "test"] = "dev"):
    response.headers["Cache-Control"] = "no-store"
    try:
        cases = load_gold(split)
        # Reads cannot seed turns, update scores, or call the classifier.
        with connect_database(read_only=True) as connection:
            return load_report(connection, cases, split)
    except psycopg.errors.UndefinedTable as error:
        raise HTTPException(
            status_code=503,
            detail="Database tables are missing. Apply schema.sql before loading results.",
        ) from error
    except psycopg.Error as error:
        # Do not expose database credentials or connection strings to the browser.
        raise HTTPException(
            status_code=503,
            detail="Cannot reach the database. Check Postgres and DATABASE_URL in .env.",
        ) from error
    except (ValueError, OSError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
