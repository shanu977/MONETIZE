# MONETIZE — Automatic Customer Detection & Tracking

> **MONETIZE — Intelligent Retail Analytics**
>
> Camera → YOLO11 → Person Detection → ByteTrack → Anonymous Customer IDs → Bounding Box + Center Coordinates → Tracking Data

## Overview

MONETIZE Intelligent Retail Analytics provides **automatic multi-person detection and tracking** from camera/video input. Every visible person receives a persistent tracking ID (`Customer_001`, `Customer_002`, etc.) with bounding boxes, center coordinates, and timestamps.

This output is designed to be consumed by **Zone System** without modification.

---

## Architecture

```
Camera/Video
    ↓
YOLO11 (yolo11n.pt)
    ↓
Person Detection (class=0)
    ↓
ByteTrack
    ↓
Customer_001, Customer_002, ...
    ↓
BBox + Center + Timestamp
    ↓
Tracking Data → Zone System
```

---

## Features

- **Automatic multi-person tracking** — No click-to-track required
- **YOLO11n** — Lightweight model for CPU inference
- **ByteTrack** — Robust tracking with ID persistence
- **Person-only filtering** — Only `person` class (COCO class 0) tracked
- **Structured output** — `track_id`, `customer_id`, `bbox`, `center`, `timestamp`, `confidence`
- **Configurable FPS** — Frame sampling for CPU-friendly processing
- **Webcam & video file support** — Switch via config or CLI
- **Real-time visualization** — Bounding boxes, IDs, center points, FPS
- **Zone System ready** — Clean `get_tracked_customers()` compatible output

---

## Installation (Windows)

```bash
# Navigate to project directory
cd MONETIZE

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Optional: GPU Support
For CUDA acceleration, install PyTorch with CUDA first:
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```
Then set `ENABLE_GPU = True` in `app/config.py` or use `--gpu` flag.

---

## Running

### Basic Usage (Webcam)
```bash
python app/main.py
```

### With Video File
```bash
python app/main.py --source "path/to/video.mp4"
```

### With Custom Settings
```bash
# Custom inference FPS (lower = less CPU usage)
python app/main.py --inference-fps 6

# Save output video
python app/main.py --save-video --output output/tracking.avi

# Use different model
python app/main.py --model yolo11s.pt

# Enable GPU
python app/main.py --gpu
```

### Command Line Options
| Option | Default | Description |
|--------|---------|-------------|
| `--source` | `0` | Video source: `0` for webcam, or path to video file |
| `--inference-fps` | `6` | Target inference FPS (0 = no limit) |
| `--save-video` | `False` | Save annotated output video |
| `--output` | `output/tracking_output.avi` | Output video path |
| `--model` | `yolo11n.pt` | YOLO model path |
| `--gpu` | `False` | Enable CUDA GPU acceleration |

---

## Configuration

Edit `app/config.py` for persistent settings:

```python
# Model
MODEL_PATH = "yolo11n.pt"

# Input source (0 = webcam, or "video.mp4")
SOURCE = 0

# Tracking
TRACKER_CONFIG = "bytetrack.yaml"
CONF_THRESHOLD = 0.3
IOU_THRESHOLD = 0.3
MAX_DET = 20

# Performance
INFERENCE_FPS = 6  # Set 0 for unlimited

# Display
SHOW_FPS = True
SHOW_CONF = False
WINDOW_NAME = "MONETIZE - Automatic Customer Tracking"

# Output
SAVE_VIDEO = False
VIDEO_OUTPUT_PATH = "output/tracking_output.avi"
```

---

## Output Data Structure

Each tracked customer produces:

```python
{
    "track_id": 1,
    "customer_id": "Customer_001",
    "class_name": "person",
    "bbox": [120, 80, 260, 420],      # [x1, y1, x2, y2]
    "center": [190, 250],              # [center_x, center_y]
    "timestamp": "2026-08-27T17:20:31.245",
    "confidence": 0.87
}
```

### Zone System Compatible Format
```python
[
    {
        "track_id": 1,
        "customer_id": "Customer_001",
        "bbox": [120, 80, 260, 420],
        "center": [190, 250],
        "timestamp": "2026-08-27T17:20:31.245"
    },
    ...
]
```

Access in code:
```python
from app.detection.detector import get_detector
from app.video.video_source import create_video_source

detector = get_detector()
video, sampler = create_video_source(0)

success, frame = video.get_frame()
if success:
    result = detector.detect_and_track(frame)
    customers = result.to_list()  # Zone System compatible
    for customer in customers:
        print(customer["customer_id"], customer["center"])
```

---

## Project Structure

```
MONETIZE/
│
├── README.md
├── requirements.txt
├── .gitignore
│
├── app/
│   ├── main.py                 # Entry point
│   ├── config.py               # Configuration
│   │
│   ├── detection/
│   │   └── detector.py         # YOLO11 + ByteTrack wrapper
│   │
│   ├── tracking/
│   │   └── tracker.py          # ByteTrack utilities
│   │
│   ├── models/
│   │   └── tracking_data.py    # Data classes (TrackedCustomer, etc.)
│   │
│   ├── video/
│   │   └── video_source.py     # Webcam/video + frame sampling
│   │
│   └── ui/
│       └── visualization.py    # Drawing & display
│
├── trackers/
│   └── bytetrack.yaml          # ByteTrack config (auto-generated)
│
├── output/
│   └── .gitkeep
│
└── tests/
    └── test_tracking_data.py
```

---

## Key Classes

| Class | Module | Purpose |
|-------|--------|---------|
| `PersonDetector` | `app.detection.detector` | YOLO11 detection + ByteTrack tracking |
| `VideoSource` | `app.video.video_source` | Camera/video input with frame sampling |
| `FrameSampler` | `app.video.video_source` | FPS limiting for CPU |
| `Visualizer` | `app.ui.visualization` | Draw boxes, IDs, centers, FPS |
| `TrackedCustomer` | `app.models.tracking_data` | Single customer tracking data |
| `TrackingResult` | `app.models.tracking_data` | Frame-level tracking container |
| `CustomerTrackerApp` | `app.main` | Main application orchestrator |

---

## ByteTrack Configuration

Default settings (in `app/config.py`):
```python
TRACKER_DEFAULTS = {
    "track_high_thresh": 0.5,    # High confidence threshold
    "new_track_thresh": 0.5,     # New track threshold
    "match_thresh": 0.8,         # Matching threshold
    "track_buffer": 30,          # Frames to keep lost tracks
    "frame_rate": 30,            # Assumed frame rate
}
```

Config file auto-generated at `trackers/bytetrack.yaml`.

---

## Testing Checklist

Run the application and verify:

- [ ] **Application starts** without errors
- [ ] **Webcam opens** (or video file plays)
- [ ] **YOLO detects people** — bounding boxes appear
- [ ] **Multiple people get different IDs** — `Customer_001`, `Customer_002`, etc.
- [ ] **IDs persist across frames** — Same person keeps same ID
- [ ] **Bounding boxes** — Correctly positioned on people
- [ ] **Center coordinates** — Displayed near center point
- [ ] **FPS displayed** — Updates in real-time
- [ ] **Tracking data produced** — Terminal logs show customer IDs & centers
- [ ] **No errors/warnings** — Clean operation

---

## Troubleshooting

### Webcam not opening
- Ensure no other app is using the camera
- Try `--source 1` or `--source 2` for secondary cameras
- Check Windows Camera privacy settings

### Low FPS on CPU
- Reduce `INFERENCE_FPS` in config (e.g., 4-6)
- Use `yolo11n.pt` (smallest model)
- Close other applications

### Model download fails
- Run once with internet to auto-download `yolo11n.pt`
- Or manually download from [Ultralytics Assets](https://github.com/ultralytics/assets/releases)

### Import errors
- Ensure virtual environment is activated
- Reinstall: `pip install -r requirements.txt --force-reinstall`

---

## Next Step: Zone System

Zone System will consume the tracking output from MONETIZE to implement:

- Zone definition (polygons/rectangles)
- Zone entry/exit detection
- Dwell time calculation
- Customer journey tracking
- Heatmap generation

The interface will be:
```python
# Zone System usage
from app.detection.detector import get_detector

detector = get_detector()
result = detector.detect_and_track(frame)
customers = result.to_part2_format()  # Ready for zone processing
```

---

## License

MONETIZE — Proprietary Product. All rights reserved.
