from __future__ import annotations
import io, json, os, tempfile, uuid, zipfile
from pathlib import Path
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from .database import SessionLocal, DrawingSession, StrokeRecord

ROOT=Path(__file__).resolve().parent.parent
EXPORTS=Path(os.getenv("AIRWRITING_EXPORTS_DIR",ROOT/"exports")).expanduser().resolve()
EXPORTS.mkdir(parents=True,exist_ok=True)
STATIC=ROOT/"airwriting"/"static"
MAX_POINTS=100_000
app=FastAPI(title="Air Writing",version="1.1.0",description="Realtime air-writing with persistent stroke history")
app.mount("/static",StaticFiles(directory=STATIC),name="static")

class StrokeIn(BaseModel):
    points:list[tuple[int,int]]=Field(min_length=1,max_length=MAX_POINTS)
    color:str=Field(default="#1565c0",pattern=r"^#[0-9a-fA-F]{6}$")
    thickness:int=Field(default=6,ge=1,le=80)
    timestamp:float|None=None
class DrawingIn(BaseModel):
    id:str|None=None
    name:str=Field(default="Untitled drawing",max_length=160)
    width:int=Field(default=1280,ge=1,le=4096)
    height:int=Field(default=800,ge=1,le=4096)
    strokes:list[StrokeIn]=Field(max_length=10_000)
    recognized_text:str|None=None

@app.get("/")
def home(): return FileResponse(STATIC/"index.html")
@app.get("/api/health")
def health(): return {"status":"ok","camera":"optional local client","database":"configured","database_url":"hidden"}
def pack(s):
    return {"id":s.id,"name":s.name,"recognized_text":s.recognized_text,"image_path":s.image_path,"created_at":s.created_at.isoformat() if s.created_at else None,"strokes":[{"points":json.loads(x.points_json),"color":x.color,"thickness":x.thickness} for x in s.strokes]}
@app.post("/api/sessions",status_code=201)
def save(d:DrawingIn):
    sid=d.id or str(uuid.uuid4())
    try: uuid.UUID(sid)
    except (ValueError,TypeError,AttributeError): raise HTTPException(422,"session id must be a UUID")
    db=SessionLocal()
    try:
        with db.begin():
            s=db.get(DrawingSession,sid)
            if s is None: s=DrawingSession(id=sid,name=d.name); db.add(s)
            s.name=d.name; s.recognized_text=d.recognized_text
            s.strokes.clear(); db.flush()
            for i,x in enumerate(d.strokes): s.strokes.append(StrokeRecord(stroke_index=i,points_json=json.dumps(x.points,separators=(",",":")),color=x.color,thickness=x.thickness))
        db.refresh(s); return pack(s)
    except Exception:
        db.rollback(); raise
    finally: db.close()
@app.get("/api/sessions")
def list_sessions():
    with SessionLocal() as db: return [pack(s) for s in db.scalars(select(DrawingSession).order_by(DrawingSession.updated_at.desc())).all()]
@app.get("/api/sessions/{sid}")
def get_session(sid:str):
    with SessionLocal() as db:
        s=db.get(DrawingSession,sid)
        if not s: raise HTTPException(404,"session not found")
        return pack(s)
@app.delete("/api/sessions/{sid}",status_code=204)
def delete_session(sid:str):
    with SessionLocal() as db:
        s=db.get(DrawingSession,sid)
        if not s: raise HTTPException(404,"session not found")
        db.delete(s); db.commit()
    return Response(status_code=204)
def render_png(strokes,width,height,scale=2):
    try: import cv2; import numpy as np
    except ImportError as e: raise HTTPException(503,"PNG export requires opencv-python and numpy") from e
    width=max(1,min(int(width),4096)); height=max(1,min(int(height),4096)); scale=max(1,min(int(scale),4))
    im=np.full((height*scale,width*scale,3),255,dtype=np.uint8)
    for s in strokes:
        pts=s["points"]
        if not pts: continue
        col=s["color"].lstrip("#"); bgr=tuple(int(col[i:i+2],16) for i in (4,2,0))
        p=np.array(pts,dtype=np.int32).reshape((-1,1,2))*scale
        p[:,:,0]=np.clip(p[:,:,0],0,width*scale-1); p[:,:,1]=np.clip(p[:,:,1],0,height*scale-1)
        thick=max(1,int(s["thickness"])*scale)
        if len(p)==1: cv2.circle(im,tuple(p[0,0]),thick//2,bgr,-1,cv2.LINE_AA)
        else: cv2.polylines(im,[p],False,bgr,thick,cv2.LINE_AA)
    ok,b=cv2.imencode(".png",im)
    if not ok: raise HTTPException(500,"PNG encoding failed")
    return b.tobytes()
@app.post("/api/export/png")
def export_png(d:DrawingIn):
    content=render_png([x.model_dump() for x in d.strokes],d.width,d.height)
    return StreamingResponse(io.BytesIO(content),media_type="image/png",headers={"Content-Disposition":"attachment; filename=airwriting.png"})
@app.get("/api/sessions/{sid}/png")
def session_png(sid:str):
    try: safe_id=str(uuid.UUID(sid))
    except ValueError: raise HTTPException(422,"session id must be a UUID")
    with SessionLocal() as db:
        s=db.get(DrawingSession,safe_id)
        if not s: raise HTTPException(404,"session not found")
        strokes=[{"points":json.loads(x.points_json),"color":x.color,"thickness":x.thickness} for x in s.strokes]
    return StreamingResponse(io.BytesIO(render_png(strokes,1280,800)),media_type="image/png",headers={"Content-Disposition":f'attachment; filename="{safe_id}.png"'})

DDL="""PRAGMA foreign_keys=ON;
CREATE TABLE sessions (id VARCHAR(36) PRIMARY KEY, name VARCHAR(160) NOT NULL, recognized_text TEXT, image_path VARCHAR(500), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
CREATE INDEX ix_sessions_created_at ON sessions(created_at);
CREATE TABLE strokes (id INTEGER PRIMARY KEY, session_id VARCHAR(36) NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, stroke_index INTEGER NOT NULL, points_json TEXT NOT NULL, color VARCHAR(16) NOT NULL, thickness INTEGER NOT NULL CHECK(thickness BETWEEN 1 AND 80), created_at DATETIME NOT NULL, UNIQUE(session_id,stroke_index));
CREATE INDEX ix_strokes_session_order ON strokes(session_id,stroke_index);
"""
DBMD="""# Air Writing database requirements

## Functional requirements
- Persist named drawing sessions and ordered strokes (JSON point arrays, color, thickness, timestamp).
- Support replay, update, list, delete, PNG export and optional recognized text.
- SQLite is the default local store; use `AIRWRITING_DATABASE_URL` for another SQLAlchemy-supported database.

## Entities
- `sessions`: UUID primary key; name (160 chars), recognized_text, image_path, created_at, updated_at.
- `strokes`: integer primary key; session_id FK with cascade delete, stroke_index, points_json, color, thickness, created_at.

## Indexes and constraints
- Index sessions.created_at; unique (strokes.session_id, strokes.stroke_index); FK cascade; thickness 1–80; transaction per save.

## Non-functional, retention and recovery
- Each save uses an atomic database transaction and rolls back on failure. SQLite connections enforce foreign keys and a 5 second busy timeout. Back up with SQLite's online backup API; keep exports separately. No automatic retention deletion is enabled; operators should define retention and encrypted backup policy.
- Store no webcam frames by default. Restrict API access if exposed beyond localhost. Configure persistent `data/` and `exports/` volumes. Export paths are application controlled and cannot be supplied by API clients.
"""
SCHEMA={"tables":{"sessions":{"id":"varchar(36) PK","name":"varchar(160)","recognized_text":"text nullable","image_path":"varchar(500) nullable","created_at":"datetime","updated_at":"datetime"},"strokes":{"id":"integer PK","session_id":"varchar(36) FK sessions.id ON DELETE CASCADE","stroke_index":"integer unique per session","points_json":"text","color":"varchar(16)","thickness":"integer 1..80","created_at":"datetime"}},"indexes":["sessions.created_at","strokes(session_id,stroke_index) unique"]}
def requirement_package_bytes():
    b=io.BytesIO()
    with zipfile.ZipFile(b,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("database_requirements.md",DBMD); z.writestr("schema.sql",DDL); z.writestr("schema.json",json.dumps(SCHEMA,indent=2))
    return b.getvalue()
def atomic_write_export(filename:str,data:bytes)->Path:
    """Atomic same-directory replacement; validated basename prevents traversal."""
    if Path(filename).name!=filename or filename in (".",".."):
        raise ValueError("export filename must be a basename")
    EXPORTS.mkdir(parents=True,exist_ok=True)
    target=(EXPORTS/filename).resolve()
    if target.parent!=EXPORTS: raise ValueError("export target escapes configured directory")
    fd,tmp_name=tempfile.mkstemp(prefix=".airwriting-",suffix=".tmp",dir=EXPORTS)
    try:
        with os.fdopen(fd,"wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp_name,target)
    except BaseException:
        try: os.unlink(tmp_name)
        except FileNotFoundError: pass
        raise
    return target
@app.get("/api/database/requirements/download")
def download_requirements():
    return StreamingResponse(io.BytesIO(requirement_package_bytes()),media_type="application/zip",headers={"Content-Disposition":"attachment; filename=airwriting_database_requirements.zip"})
@app.post("/api/database/requirements/export")
def export_requirements():
    """FastAPI runs this synchronous function in its worker pool, outside realtime CV processing."""
    try: target=atomic_write_export("airwriting_database_requirements.zip",requirement_package_bytes())
    except OSError as exc: raise HTTPException(500,f"Could not write export: {exc}") from exc
    return {"saved_to":str(target)}
