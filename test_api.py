import sys
from pathlib import Path
sys.path.insert(0, ".")
from app.api.main import app
from fastapi.testclient import TestClient
client = TestClient(app)

print("Testing real API endpoints...")

# Test cameras
print("\n=== /api/cameras ===")
r = client.get("/api/cameras")
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Test demo status
print("\n=== /api/demo/status ===")
r = client.get("/api/demo/status")
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Test maps
print("\n=== /api/maps ===")
r = client.get("/api/maps")
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Test active camera
print("\n=== /api/cameras/active/status ===")
r = client.get("/api/cameras/active/status")
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Test runtime status
print("\n=== /api/runtime/status ===")
r = client.get("/api/runtime/status")
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Test customers
print("\n=== /api/customers ===")
r = client.get("/api/customers")
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Test zones
print("\n=== /api/zones ===")
r = client.get("/api/zones")
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Test cctv status
print("\n=== /api/cctv/status ===")
r = client.get("/api/cctv/status")
print(f"Status: {r.status_code}")
print(f"Response: {r.json()}")

# Test cctv stream (should return MJPEG)
print("\n=== /api/cctv/stream ===")
r = client.get("/api/cctv/stream", headers={"Accept": "multipart/x-mixed-replace"})
print(f"Status: {r.status_code}")
print(f"Content-Type: {r.headers.get('content-type')}")
print(f"Response preview: {r.text[:200]}...")