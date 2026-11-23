"""FastAPI entry point: python run_server.py [--host 127.0.0.1 --port 8000]."""
import argparse
import uvicorn
p=argparse.ArgumentParser(description="Run Air Writing Studio")
p.add_argument("--host",default="127.0.0.1")
p.add_argument("--port",type=int,default=8000)
p.add_argument("--reload",action="store_true")
a=p.parse_args()
uvicorn.run("airwriting.main:app",host=a.host,port=a.port,reload=a.reload)
