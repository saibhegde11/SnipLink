from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, Field
from fastapi.responses import RedirectResponse
import secrets
from storage_practice import (
    initialize_database,
    save_link as create_link,
    find_link,
    delete_link,
    count_links,
    find_link_details,
    record_click,
    get_click_count
)
import expiry_practice as expiry 
import cache_practice as cache
from redis.exceptions import RedisError

initialize_database()

class createLinkRequest(BaseModel) : 
    short_code : str | None = Field(
        default= None,
        min_length=3,
        max_length=20, 
        pattern="^[A-Za-z0-9_-]+$"
        # ^ -> start of the string
        # A-Za-z0-9_- -> allowed characters
        # + -> one or more times
        # $ -> end of the string
    )
    original_url : HttpUrl
    expires_in : int | None = Field(
        default=None,
        ge=1,
        le=31_536_000,
        strict=True
    )

def generate_short_code() : 
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_-"
    short_code = ""
    for _ in range(6) : 
        short_code += secrets.choice(alphabet)
    
    return short_code

def create_generated_link(original_url, expires_at = None) : 
    for _ in range(5) :
        candidate = generate_short_code()

        try : 
            return create_link(candidate, original_url, expires_at)
        except ValueError : 
            continue

    return None

app = FastAPI()

@app.get("/health")
def health() : 
    return {"status" : "ok"}

@app.get("/links/{short_code}")
def read_link(short_code : str) : 
    original_url = find_link(short_code)
    if original_url is None : 
        raise HTTPException(
            status_code=404, 
            detail="Short Code not Found"
        )
    return {
        "short_code" : short_code,
        "original_url" : original_url
    }

@app.delete("/links/{short_code}") 
def remove_link(short_code : str) :
    if delete_link(short_code) : 
        try : 
            cache.delete_cached_link(short_code)
        except RedisError : 
            pass
        return {"Deleted" : True}
    raise HTTPException(
        status_code=404,
        detail="Short Code not Found"
    )

@app.post("/links", status_code=201)
def add_link(body : createLinkRequest) : 
    original_url = str(body.original_url)
    expires_at = expiry.calculate_expiry(
        body.expires_in,
        expiry.current_timestamp()
    )
    if body.short_code is None : 
        short_code = create_generated_link(original_url, expires_at)

        if short_code is None : 
            raise HTTPException(
                status_code=503,
                detail="Could not generate short code"
            )
    else :
        try : 
            short_code = create_link(
                body.short_code,
                original_url,
                expires_at
            )
        except ValueError as error : 
            raise HTTPException(
                status_code=409, 
                detail=str(error)
            )
    return {
        "short_code" : short_code,
        "original_url" : original_url,
        "redirect_url" : f"http://127.0.0.1:8000/r/{short_code}",
        "expires_at" : expires_at
    }
@app.get("/stats")
def get_stats() : 
    total_cnt = count_links()
    return {
        "total_links" : total_cnt
    }

def find_link_with_cache(short_code : str, force_refresh : bool = False) -> dict | None : 
    if not force_refresh : 
        try : 
            details = cache.get_cached_link(short_code)
        except RedisError : 
            details = None
        if details is not None : 
            return details
    
    details = find_link_details(short_code) 
    if details is not None : 
        try : 
            cache.cache_link_with_expiry(
                short_code, 
                details,
                expiry.current_timestamp()
            )
        except RedisError : 
            pass
    
    return details

@app.get("/r/{short_code}")
def open_link(short_code : str) : 
    details = find_link_with_cache(short_code)
    for attempt in range(2) : 
        if details is None : 
            raise HTTPException(
                status_code=404, 
                detail="Short Code not Found"
            )
        expired = expiry.is_expired(
            details["expires_at"], 
            expiry.current_timestamp()
        )
        if expired and attempt == 0 : 
            details = find_link_with_cache(short_code, True)
            continue
        if expired and attempt == 1 : 
            raise HTTPException(
                status_code=410,
                detail="Short Code Expired"
            )
        recorded = record_click(
            short_code, 
            details["original_url"],
            details["expires_at"]
        )
        if recorded : 
            return RedirectResponse(
                status_code=302,
                url=details["original_url"]
            )
        
        if attempt == 0 : 
            details = find_link_with_cache(short_code, True)
            continue

    raise HTTPException(
        status_code=503,
        detail="Link changed during redirect; please retry"
    )

@app.get("/links/{short_code}/stats")
def read_link_stats(short_code : str) : 
    count = get_click_count(short_code)
    if count is None : 
        raise HTTPException(
            status_code=404,
            detail="Short Code Not Found"
        )
    return {
        "short_code" : short_code,
        "count" : count
    }
