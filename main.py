# ================================================================
# RENDER CLOUD SERVER — WEBSOCKET STREAM (FIXED FOR STABILITY)
# ================================================================
# Fixed to handle the WebSocket connection without timeouts
# or memory issues
# ================================================================

import os
import cv2
import numpy as np
import mediapipe as mp
import time
from flask import Flask
from flask_sock import Sock

app = Flask(__name__)
sock = Sock(app)

# ── MediaPipe Setup (GLOBAL, not per-connection) ───────────────
# This is fine because flask_sock handles concurrency with gevent
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    model_complexity=0,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

# ── Constants ──────────────────────────────────────────────────
MIN_FRAME_BYTES = 100
MAX_FRAME_BYTES = 20000
MP_INTERVAL     = 0.05  # Process at 20fps max


# ── Gesture Classifier ─────────────────────────────────────────
def detect_gesture(landmarks):
    tip_ids = [4, 8, 12, 16, 20]
    fingers = []

    if landmarks[tip_ids[0]].x < landmarks[tip_ids[0] - 1].x:
        fingers.append(1)
    else:
        fingers.append(0)

    for i in range(1, 5):
        if landmarks[tip_ids[i]].y < landmarks[tip_ids[i] - 2].y:
            fingers.append(1)
        else:
            fingers.append(0)

    total = sum(fingers)
    if total == 5:                          return "HELLO"
    if total == 0:                          return "EMERGENCY"
    if total == 2:                          return "YES"
    if total == 1:                          return "WATER"
    if total == 3:                          return "FOOD"
    if total == 4:                          return "MEDICINE"
    if fingers == [1, 0, 0, 0, 0]:         return "REST"
    return "Searching..."


# ── Health Check ───────────────────────────────────────────────
@app.route('/')
@app.route('/healthz')
def health_check():
    return "AI Core Online", 200


# ── WebSocket Handler ──────────────────────────────────────────
@sock.route('/')
def handle_esp32_client(ws):
    print("[CLOUD] ESP32 client connected!")
    
    last_mp_time = 0
    frames_received = 0

    try:
        while True:
            # Receive with timeout
            try:
                data = ws.receive(timeout=60)  # 60 second timeout
            except Exception as recv_err:
                print(f"[DISCONNECT] Receive error: {recv_err}")
                break

            if data is None:
                print("[DISCONNECT] Client closed")
                break

            # Type check
            if not isinstance(data, (bytes, bytearray)):
                continue

            frame_len = len(data)
            frames_received += 1

            # ── Frame validation ──
            if frame_len < MIN_FRAME_BYTES or frame_len > MAX_FRAME_BYTES:
                continue

            # ── Throttle MediaPipe ──
            now = time.time()
            if now - last_mp_time < MP_INTERVAL:
                continue
            last_mp_time = now

            # ── Process frame ──
            try:
                np_arr = np.frombuffer(data, dtype=np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

                if frame is None:
                    continue

                h, w = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Run MediaPipe
                results = hands.process(rgb)

                gesture = "Searching..."
                coords = ""

                if results.multi_hand_landmarks:
                    for lms in results.multi_hand_landmarks:
                        detected = detect_gesture(lms.landmark)
                        if detected:
                            gesture = detected

                        # Map coordinates
                        coord_list = []
                        for lm in lms.landmark:
                            px = max(0, min(int(lm.x * w), w - 1))
                            py = max(0, min(int(lm.y * h), h - 1))
                            coord_list.append(f"{px},{py}")
                        coords = ";".join(coord_list)

                payload = f"{gesture}|{coords}" if coords else f"{gesture}|NODATA"
                ws.send(payload)

                # Log every 50 frames
                if frames_received % 50 == 0:
                    print(f"[ENGINE] Gesture={gesture} | Frame={frame_len}B | Total={frames_received}")

            except Exception as proc_err:
                # Frame processing error - don't crash, just skip
                print(f"[ERROR] Frame {frames_received} failed: {type(proc_err).__name__}")
                try:
                    ws.send("Searching...|NODATA")
                except Exception:
                    break

    except Exception as fatal_err:
        print(f"[FATAL] Handler error: {fatal_err}")

    finally:
        print(f"[CLOUD] Client disconnected after {frames_received} frames")


# ── Launch ────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
