import os
import subprocess
import threading
import time
import webview
import requests



base_path = os.path.dirname(os.path.abspath(__file__))
os.chdir(base_path)

# Launch backend (FastAPI)
def start_backend():
    subprocess.Popen(
        ["uvicorn", "backend:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=base_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

# Launch frontend (Streamlit)
def start_frontend():
    subprocess.Popen(
        ["streamlit", "run", "DT.py", "--server.headless=true", "--browser.serverAddress=127.0.0.1"],
        cwd=base_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

# Check if Streamlit is live
def wait_for_streamlit():
    max_tries = 20
    for _ in range(max_tries):
        try:
            r = requests.get("http://127.0.0.1:8501")
            if r.status_code == 200:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(1)
    return False

# Start both in background threads
threading.Thread(target=start_backend, daemon=True).start()
time.sleep(2)
threading.Thread(target=start_frontend, daemon=True).start()

# Wait for Streamlit to be ready
if wait_for_streamlit():
    webview.create_window("BSE Dummy Trading App", "http://127.0.0.1:8501", width=1300, height=800)
    webview.start()
else:
    print("Streamlit failed to start. Please check DT.py for errors.")
