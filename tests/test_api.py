import io, zipfile
from uuid import uuid4
from fastapi.testclient import TestClient
from airwriting.main import app, EXPORTS
from airwriting.database import engine
from sqlalchemy import inspect

client=TestClient(app)
def test_import_and_schema():
    tables=set(inspect(engine).get_table_names()); assert {"sessions","strokes"} <= tables
    assert {"id","name","recognized_text","image_path","created_at","updated_at"} <= {c["name"] for c in inspect(engine).get_columns("sessions")}
    assert {"session_id","stroke_index","points_json","color","thickness"} <= {c["name"] for c in inspect(engine).get_columns("strokes")}
def test_health_and_ui():
    assert client.get("/api/health").status_code==200
    assert "Air Writing" in client.get("/").text
def test_save_list_get_delete_round_trip():
    sid=str(uuid4()); payload={"id":sid,"name":"test drawing","width":320,"height":200,"strokes":[{"points":[[2,3],[40,50]],"color":"#123abc","thickness":5}]}
    saved=client.post("/api/sessions",json=payload); assert saved.status_code==201,saved.text
    assert saved.json()["strokes"][0]["points"]==[[2,3],[40,50]]
    assert client.get("/api/sessions/"+sid).status_code==200
    assert any(x["id"]==sid for x in client.get("/api/sessions").json())
    assert client.delete("/api/sessions/"+sid).status_code==204
    assert client.get("/api/sessions/"+sid).status_code==404
def test_png_export():
    payload={"width":100,"height":80,"strokes":[{"points":[[1,1],[90,70]],"color":"#ff0000","thickness":4}]}
    r=client.post("/api/export/png",json=payload)
    assert r.status_code==200 and r.headers["content-type"]=="image/png"
    assert r.content[:8]==b"\x89PNG\r\n\x1a\n"
def test_requirements_zip_and_atomic_export():
    r=client.get("/api/database/requirements/download")
    assert r.status_code==200 and "attachment" in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert set(z.namelist())=={"database_requirements.md","schema.sql","schema.json"}
        assert "retention" in z.read("database_requirements.md").decode().lower()
    out=client.post("/api/database/requirements/export"); assert out.status_code==200,out.text
    path=EXPORTS/"airwriting_database_requirements.zip"; assert path.is_file()
    with zipfile.ZipFile(path) as z: assert "schema.sql" in z.namelist()
def test_session_png_and_invalid_session_id():
    sid=str(uuid4()); assert client.post("/api/sessions",json={"id":sid,"strokes":[]}).status_code==201
    r=client.get(f"/api/sessions/{sid}/png"); assert r.status_code==200 and r.content.startswith(b"\x89PNG")
    assert client.get("/api/sessions/../../etc/passwd/png").status_code in (404,422)
def test_reject_bad_stroke_fields():
    r=client.post("/api/sessions",json={"strokes":[{"points":[[0,0]],"color":"red"}]})
    assert r.status_code==422
def test_mediapipe_hand_model_initializes_and_closes():
    import mediapipe as mp
    from pathlib import Path
    model=Path(__file__).resolve().parents[1]/"models"/"hand_landmarker.task"
    assert model.is_file()
    opts=mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=.65,
        min_hand_presence_confidence=.65,
        min_tracking_confidence=.65,
    )
    task=mp.tasks.vision.HandLandmarker.create_from_options(opts)
    task.close()
def test_stroke_manager_breaks_large_jumps():
    from airwriting.engine import StrokeManager
    manager=StrokeManager(); assert manager.add((10,10)) is False
    assert manager.add((20,20)) is True
    assert manager.add((1000,700)) is False
    assert len(manager.strokes)==2
    assert manager.strokes[0].points==[(10,10),(20,20)]
    assert manager.strokes[1].points==[(1000,700)]
def test_export_rejects_path_traversal():
    import pytest
    from airwriting.main import atomic_write_export
    with pytest.raises(ValueError):
        atomic_write_export("../outside.zip",b"unsafe")
