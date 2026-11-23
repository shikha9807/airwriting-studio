"""OpenCV entry point. Configure with AIRWRITING_CAMERA_INDEX, AIRWRITING_RECONNECT_ATTEMPTS, AIRWRITING_HAND_MODEL."""
import argparse
import os
from airwriting.engine import run_opencv_camera
p=argparse.ArgumentParser(description="Run the OpenCV air-writing HUD; q/Escape exits, c clears, u undoes")
p.add_argument("--camera",type=int,default=int(os.getenv("AIRWRITING_CAMERA_INDEX","0")))
p.add_argument("--reconnect-attempts",type=int,default=int(os.getenv("AIRWRITING_RECONNECT_ATTEMPTS","0")),help="0 retries forever")
a=p.parse_args()
run_opencv_camera(a.camera,max_reconnect_attempts=a.reconnect_attempts)
