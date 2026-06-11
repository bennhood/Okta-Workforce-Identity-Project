"""
scim_server.py
A minimal SCIM 2.0 service provider for the AcmeCorp IAM lab.

Okta acts as the SCIM client (identity source). This server is the SCIM
target. When users are assigned to the SCIM app in Okta, Okta emits standard
SCIM 2.0 protocol calls to this server:

    GET    /scim/v2/Users?filter=userName eq "..."   check before create
    POST   /scim/v2/Users                            create   (Joiner)
    PUT    /scim/v2/Users/{id}                        replace  (Mover)
    PATCH  /scim/v2/Users/{id}                        active=false (Leaver)
    DELETE /scim/v2/Users/{id}                        delete
    GET    /scim/v2/Users                             import / list

Every inbound call is logged to stdout and to an in-memory feed viewable at
the root URL ("/"). Those logged JSON payloads ARE the SCIM protocol - they
are the evidence that this is genuine SCIM, not vendor-API automation.

Auth: OAuth Bearer Token. Okta sends `Authorization: Bearer <token>` where
<token> is the value entered in the Okta app's "API token" field. Set the
same value here via the SCIM_TOKEN environment variable.

Run locally:   uvicorn scim_server:app --host 0.0.0.0 --port 8000
Then expose:   ngrok http 8000   (use the https URL + /scim/v2 as Base URL)
Or deploy free on Render / Railway (see deploy notes).
"""

import os
import re
import uuid
import json
import datetime

from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.responses import JSONResponse, HTMLResponse

# Shared secret - must match the "API token" entered in the Okta SCIM app
SCIM_TOKEN = os.environ.get("SCIM_TOKEN", "place_generated_token_here")

app = FastAPI(title="AcmeCorp SCIM 2.0 Server")

# In-memory stores. Resets on restart - fine for a lab demonstration.
users = {}          # id -> user record
groups = {}         # id -> group record
request_feed = []   # recent SCIM calls, newest first, for the dashboard

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def scim_error(status, detail):
    return JSONResponse(
        status_code=status,
        content={"schemas": [ERROR_SCHEMA], "status": str(status), "detail": detail}
    )


# ---------------------------------------------------------------------------
# Auth + request logging
# ---------------------------------------------------------------------------

def require_auth(authorization: str = Header(None)):
    """Validate the OAuth bearer token Okta sends on every SCIM call."""
    if authorization != f"Bearer {SCIM_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")


@app.middleware("http")
async def log_scim_calls(request: Request, call_next):
    """Log every inbound SCIM call (method, path, body) for the evidence feed."""
    if request.url.path.startswith("/scim"):
        raw = await request.body()
        body = None
        if raw:
            try:
                body = json.loads(raw)
            except Exception:
                body = raw.decode(errors="ignore")
        entry = {
            "time": now_iso(),
            "method": request.method,
            "path": request.url.path + (f"?{request.url.query}" if request.url.query else ""),
            "body": body,
        }
        request_feed.insert(0, entry)
        del request_feed[50:]
        print(f"[SCIM] {entry['time']} {entry['method']} {entry['path']}")
        if body:
            print("       " + json.dumps(body))

    return await call_next(request)


# ---------------------------------------------------------------------------
# SCIM resource builders
# ---------------------------------------------------------------------------

def to_scim_user(u):
    return {
        "schemas": [USER_SCHEMA],
        "id": u["id"],
        "userName": u["userName"],
        "name": u.get("name", {}),
        "displayName": u.get("displayName", ""),
        "emails": u.get("emails", []),
        "active": u.get("active", True),
        "meta": {
            "resourceType": "User",
            "created": u["created"],
            "lastModified": u["lastModified"],
            "location": f"/scim/v2/Users/{u['id']}",
        },
    }


def to_scim_group(g):
    return {
        "schemas": [GROUP_SCHEMA],
        "id": g["id"],
        "displayName": g["displayName"],
        "members": g.get("members", []),
        "meta": {
            "resourceType": "Group",
            "created": g["created"],
            "lastModified": g["lastModified"],
            "location": f"/scim/v2/Groups/{g['id']}",
        },
    }


def list_response(resources, start_index=1):
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": len(resources),
        "startIndex": start_index,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


# ---------------------------------------------------------------------------
# Discovery - Okta probes this when testing credentials
# ---------------------------------------------------------------------------

@app.get("/scim/v2/ServiceProviderConfig")
def service_provider_config(auth=Depends(require_auth)):
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": False},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {"name": "OAuth Bearer Token", "type": "oauthbearertoken"}
        ],
    }


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@app.get("/scim/v2/Users")
def list_users(filter: str = None, startIndex: int = 1, count: int = 100,
               auth=Depends(require_auth)):
    """List or filter users. Okta filters by userName before creating."""
    results = list(users.values())

    if filter:
        match = re.match(r'userName eq "(.+?)"', filter)
        if match:
            wanted = match.group(1)
            results = [u for u in results if u["userName"] == wanted]

    page = results[startIndex - 1: startIndex - 1 + count]
    return list_response([to_scim_user(u) for u in page], startIndex)


@app.post("/scim/v2/Users")
async def create_user(request: Request, auth=Depends(require_auth)):
    """Create a user (Joiner). Returns 201 with the created resource."""
    payload = await request.json()
    user_name = payload.get("userName")

    # Idempotency - if userName already exists, return the existing resource
    for u in users.values():
        if u["userName"] == user_name:
            return JSONResponse(status_code=409, content={
                "schemas": [ERROR_SCHEMA], "status": "409",
                "detail": "User already exists", "scimType": "uniqueness"
            })

    uid = str(uuid.uuid4())
    ts = now_iso()
    users[uid] = {
        "id": uid,
        "userName": user_name,
        "name": payload.get("name", {}),
        "displayName": payload.get("displayName", ""),
        "emails": payload.get("emails", []),
        "active": payload.get("active", True),
        "created": ts,
        "lastModified": ts,
    }
    return JSONResponse(status_code=201, content=to_scim_user(users[uid]))


@app.get("/scim/v2/Users/{uid}")
def get_user(uid: str, auth=Depends(require_auth)):
    if uid not in users:
        return scim_error(404, "User not found")
    return to_scim_user(users[uid])


@app.put("/scim/v2/Users/{uid}")
async def replace_user(uid: str, request: Request, auth=Depends(require_auth)):
    """Full replace (Mover - attribute or group changes)."""
    if uid not in users:
        return scim_error(404, "User not found")
    payload = await request.json()
    u = users[uid]
    u["userName"] = payload.get("userName", u["userName"])
    u["name"] = payload.get("name", u.get("name", {}))
    u["displayName"] = payload.get("displayName", u.get("displayName", ""))
    u["emails"] = payload.get("emails", u.get("emails", []))
    u["active"] = payload.get("active", u.get("active", True))
    u["lastModified"] = now_iso()
    return to_scim_user(u)


@app.patch("/scim/v2/Users/{uid}")
async def patch_user(uid: str, request: Request, auth=Depends(require_auth)):
    """
    Partial update. Okta sends this to deactivate a user (Leaver):
    {"Operations":[{"op":"replace","value":{"active":false}}]}
    Both the path-based and value-object forms are handled.
    """
    if uid not in users:
        return scim_error(404, "User not found")
    payload = await request.json()
    u = users[uid]

    for op in payload.get("Operations", []):
        path = op.get("path")
        value = op.get("value")

        if path == "active":
            u["active"] = value if not isinstance(value, list) else value[0].get("value")
        elif isinstance(value, dict):
            if "active" in value:
                u["active"] = value["active"]
            for attr in ("displayName", "name", "emails"):
                if attr in value:
                    u[attr] = value[attr]

    u["lastModified"] = now_iso()
    return to_scim_user(u)


@app.delete("/scim/v2/Users/{uid}")
def delete_user(uid: str, auth=Depends(require_auth)):
    if uid not in users:
        return scim_error(404, "User not found")
    del users[uid]
    return JSONResponse(status_code=204, content=None)


# ---------------------------------------------------------------------------
# Groups (minimal - supports the Import Groups option)
# ---------------------------------------------------------------------------

@app.get("/scim/v2/Groups")
def list_groups(startIndex: int = 1, count: int = 100, auth=Depends(require_auth)):
    page = list(groups.values())[startIndex - 1: startIndex - 1 + count]
    return list_response([to_scim_group(g) for g in page], startIndex)


@app.post("/scim/v2/Groups")
async def create_group(request: Request, auth=Depends(require_auth)):
    payload = await request.json()
    gid = str(uuid.uuid4())
    ts = now_iso()
    groups[gid] = {
        "id": gid,
        "displayName": payload.get("displayName", ""),
        "members": payload.get("members", []),
        "created": ts,
        "lastModified": ts,
    }
    return JSONResponse(status_code=201, content=to_scim_group(groups[gid]))


@app.get("/scim/v2/Groups/{gid}")
def get_group(gid: str, auth=Depends(require_auth)):
    if gid not in groups:
        return scim_error(404, "Group not found")
    return to_scim_group(groups[gid])


@app.delete("/scim/v2/Groups/{gid}")
def delete_group(gid: str, auth=Depends(require_auth)):
    if gid not in groups:
        return scim_error(404, "Group not found")
    del groups[gid]
    return JSONResponse(status_code=204, content=None)


# ---------------------------------------------------------------------------
# Evidence dashboard - open the root URL to see live SCIM traffic
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard():
    rows = ""
    for e in request_feed:
        body = json.dumps(e["body"], indent=2) if e["body"] else ""
        rows += (
            f"<tr><td>{e['time']}</td><td><b>{e['method']}</b></td>"
            f"<td>{e['path']}</td><td><pre>{body}</pre></td></tr>"
        )
    if not rows:
        rows = "<tr><td colspan=4>No SCIM calls received yet.</td></tr>"

    return f"""
    <html><head><title>AcmeCorp SCIM 2.0 Server</title>
    <style>
      body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
      h1 {{ font-size: 1.2rem; }}
      table {{ border-collapse: collapse; width: 100%; }}
      td, th {{ border: 1px solid #ddd; padding: 6px; vertical-align: top;
                font-size: 0.85rem; text-align: left; }}
      pre {{ margin: 0; white-space: pre-wrap; }}
      .meta {{ color: #666; }}
    </style></head>
    <body>
      <h1>AcmeCorp SCIM 2.0 Server</h1>
      <p class="meta">Live feed of inbound SCIM protocol calls from Okta.
      {len(users)} user(s), {len(groups)} group(s) currently stored.</p>
      <table>
        <tr><th>Time (UTC)</th><th>Method</th><th>Path</th><th>Payload</th></tr>
        {rows}
      </table>
    </body></html>
    """


@app.get("/health")
def health():
    return {"status": "ok", "users": len(users), "groups": len(groups)}
