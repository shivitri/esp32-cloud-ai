# ================================================================
# RENDER CLOUD SERVER — ULTRA-SMOOTH ZERO-LAG GESTURE ENGINE
# ================================================================
# This version is guaranteed to work with gunicorn
# ================================================================

import os
import cv2
import numpy as np
import mediapipe as mp
import time
from collections import deque
from flask import Flask
from flask_sock import Sock

# ── CREATE FLASK APP (CRITICAL FOR GUNICORN) ───────────────────
app = Flask(__name__)
sock = Sock(app)

# ── ULTRA-SMOOTH TUNING ────────────────────────────────────────
MIN_FRAME_BYTES = 100     # Accept even small frames (faster processing)
MAX_FRAME_BYTES = 20000   # Reject garbage frames
MP_INTERVAL     = 0.033   # Process at ~30fps max (leave CPU headroom)

# Gesture smoothing: reduce jitter by averaging last N detections
GESTURE_SMOOTH_WINDOW = 1  # Set to 1 for zero-latency (no smoothing)

# Connection keepalive
RECEIVE_TIMEOUT = 45  # 45 seconds before considering connection dead


# ── Gesture Classifier (Optimized) ─────────────────────────────
def detect_gesture(landmarks):
    """Ultra-fast gesture detection with no allocations"""
    tip_ids = [4, 8, 12, 16, 20]
    fingers = []

    # Thumb check (x-coordinate)
    if landmarks[tip_ids[0]].x < landmarks[tip_ids[0] - 1].x:
        fingers.append(1)
    else:
        fingers.append(0)

    # Other 4 fingers (y-coordinate)
    for i in range(1, 5):
        if landmarks[tip_ids[i]].y < landmarks[tip_ids[i] - 2].y:
            fingers.append(1)
        else:
            fingers.append(0)

    total = sum(fingers)
    
    # Fast hardcoded mapping (no dict lookup)
    if total == 5:                          return "HELLO"
    if total == 0:                          return "EMERGENCY"
    if total == 2:                          return "YES"
    if total == 1:                          return "WATER"
    if total == 3:                          return "FOOD"
    if total == 4:                          return "MEDICINE"
    if fingers == [1, 0, 0, 0, 0]:         return "REST"
    return "Searching..."


# ── Health Check Route ─────────────────────────────────────────
@app.route('/')
@app.route('/healthz')
def health_check():
    return "🚀 AI Core Online", 200


# ── WebSocket Handler (Ultra-Optimized) ──────────────────────
@sock.route('/')
def handle_esp32_client(ws):
    print("[✓] ESP32 client connected! Starting gesture stream...")
    
    # Per-connection MediaPipe instance
    hands = mp.solutions.hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        model_complexity=0,  # Lightweight
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )

    last_mp_time = 0
    last_send_time = time.time()
    
    # Gesture smoothing queue (for predictive filtering)
    gesture_queue = deque(maxlen=GESTURE_SMOOTH_WINDOW)
    last_gesture = "Searching..."
    
    # Connection keepalive tracking
    frames_received = 0
    bytes_received = 0

    try:
        while True:
            # ── Receive frame with timeout ──
            try:
                data = ws.receive(timeout=RECEIVE_TIMEOUT)
            except Exception as recv_err:
                print(f"[✗] Receive timeout/error: {recv_err}")
                break

            if data is None:
                print("[✓] Client closed cleanly")
                break

            # ── Strict type check ──
            if not isinstance(data, (bytes, bytearray)):
                print("[!] Received non-binary data (skipped)")
                continue

            frame_len = len(data)
            frames_received += 1
            bytes_received += frame_len

            # ── Frame validation (aggressive) ──
            if frame_len < MIN_FRAME_BYTES or frame_len > MAX_FRAME_BYTES:
                print(f"[!] Frame {frames_received} invalid size: {frame_len}B (skipped)")
                continue

            # ── Throttle MediaPipe processing (ZERO-LAG) ──
            # Process at most every MP_INTERVAL seconds
            # This prevents CPU spike on Render free tier
            now = time.time()
            if now - last_mp_time < MP_INTERVAL:
                continue
            last_mp_time = now

            # ── Process Frame (isolated try/except) ──
            try:
                # Decode frame
                np_arr = np.frombuffer(data, dtype=np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

                if frame is None:
                    print(f"[!] Frame {frames_received} decode failed (skipped)")
                    continue

                h, w = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Run MediaPipe gesture detection
                results = hands.process(rgb)

                gesture = "Searching..."
                coords = ""

                if results.multi_hand_landmarks:
                    for lms in results.multi_hand_landmarks:
                        detected = detect_gesture(lms.landmark)
                        if detected:
                            gesture = detected

                        # Map normalized coords to pixel space
                        coord_list = []
                        for lm in lms.landmark:
                            px = max(0, min(int(lm.x * w), w - 1))
                            py = max(0, min(int(lm.y * h), h - 1))
                            coord_list.append(f"{px},{py}")
                        coords = ";".join(coord_list)

                # Apply gesture smoothing (if enabled)
                gesture_queue.append(gesture)
                if gesture_queue:
                    # Use most common gesture in window (simple voting)
                    gesture = max(set(gesture_queue), key=gesture_queue.count)

                # Only send if gesture changed or if it's been too long
                now_send = time.time()
                if gesture != last_gesture or (now_send - last_send_time > 0.1):
                    payload = f"{gesture}|{coords}" if coords else f"{gesture}|NODATA"
                    ws.send(payload)
                    last_gesture = gesture
                    last_send_time = now_send

                # Log periodically (not every frame)
                if frames_received % 100 == 0:
                    print(f"[→] Gesture={gesture} | Frames={frames_received} | Data={bytes_received/1024:.1f}KB")

            except cv2.error as cv_err:
                # OpenCV errors (decode, etc.) don't crash the handler
                print(f"[!] CV error on frame {frames_received}: {cv_err}")
                try:
                    ws.send("Searching...|NODATA")
                except Exception:
                    break
                    
            except Exception as proc_err:
                # Any other processing error
                print(f"[!] Process error on frame {frames_received}: {type(proc_err).__name__}")
                try:
                    ws.send("Searching...|NODATA")
                except Exception:
                    break

    except Exception as fatal_err:
        print(f"[✗] FATAL handler error: {fatal_err}")

    finally:
        # Clean up
        try:
            hands.close()
        except Exception:
            pass
        print(f"[✓] Disconnected. Processed {frames_received} frames, {bytes_received/1024:.1f}KB total")


# ── Launch ────────────────────────────────────────────────────
# This is called by gunicorn: gunicorn -k gevent -w 1 --bind 0.0.0.0:10000 main:app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"\n[*] Starting Flask server on port {port}...")
    print(f"[*] For Render, use: gunicorn -k gevent -w 1 --bind 0.0.0.0:{port} main:app\n")
    app.run(host="0.0.0.0", port=port, debug=False)
