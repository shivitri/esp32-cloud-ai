# ================================================================
# RENDER CLOUD SERVER — FIXED ROBUST WEBSOCKET + MEDIAPIPE ENGINE
# ================================================================
# ROOT CAUSE FIXES APPLIED:
#   [1] Per-connection MediaPipe Hands() instance (was shared/unsafe)
#   [2] Frame size validation (reject garbage frames before decode)
#   [3] Two-level exception handling (processing errors don't kill connection)
#   [4] Throttled MP processing to avoid CPU backpressure on Render free tier
#   [5] Proper cleanup of MediaPipe on every disconnect
#
# RENDER DEPLOYMENT:
#   Start Command: gunicorn -k gevent -w 1 server:app
#   (Replace "server" with your actual filename without .py)
#   Add to requirements.txt: gunicorn, gevent
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

# ── Constants ──────────────────────────────────────────────────
MIN_FRAME_BYTES = 200    # Reject tiny/corrupt frames
MAX_FRAME_BYTES = 20000  # Reject frames too large (malformed)
MP_INTERVAL     = 0.05   # Max 20fps through MediaPipe (CPU budget)


# ── Gesture Classifier ─────────────────────────────────────────
def detect_gesture(landmarks):
    tip_ids = [4, 8, 12, 16, 20]
    fingers = []

    # Thumb: compare x (horizontal)
    if landmarks[tip_ids[0]].x < landmarks[tip_ids[0] - 1].x:
        fingers.append(1)
    else:
        fingers.append(0)

    # Other 4 fingers: compare y (vertical, tip vs pip)
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


# ── Health Check (keeps Render service alive) ─────────────────
@app.route('/')
@app.route('/healthz')
def health_check():
    return "AI Core Online", 200


# ── WebSocket Handler ─────────────────────────────────────────
@sock.route('/')
def handle_esp32_client(ws):
    print("[CLOUD] ESP32 client connected!")

    # FIX [1]: Each new connection creates its OWN MediaPipe instance.
    # The old code used a single global `hands` object. If the ESP32
    # reconnected, the same instance was reused across threads/calls,
    # causing state corruption and crashes.
    hands = mp.solutions.hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        model_complexity=0,          # Lightweight model for free-tier CPU
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )

    last_mp_time = 0

    try:
        while True:
            # ── Receive frame (blocks until data or disconnect) ──
            try:
                data = ws.receive(timeout=30)
            except Exception as recv_err:
                # ConnectionClosed, timeout, or socket error
                print(f"[CLOUD] Receive ended: {recv_err}")
                break

            if data is None:
                print("[CLOUD] Client closed connection cleanly")
                break

            # Only accept binary (JPEG frame) data
            if not isinstance(data, (bytes, bytearray)):
                continue

            # FIX [2]: Validate frame size BEFORE trying to decode.
            # A corrupt/empty frame passed to cv2.imdecode can raise
            # an unhandled C++ exception that kills the process on Render.
            frame_len = len(data)
            if frame_len < MIN_FRAME_BYTES or frame_len > MAX_FRAME_BYTES:
                print(f"[CLOUD] Skipping invalid frame size: {frame_len} bytes")
                continue

            # FIX [4]: Throttle MediaPipe — don't process every frame.
            # The ESP32 sends ~7fps. We process at most 20fps equivalent,
            # but this cap prevents CPU spikes on Render's free tier.
            now = time.time()
            if now - last_mp_time < MP_INTERVAL:
                continue
            last_mp_time = now

            # ── Frame Processing (FIX [3]: isolated try/except) ──
            # Processing errors (bad decode, MP crash) are caught here
            # and do NOT break the outer while loop. The connection stays
            # alive and we just skip that one frame.
            try:
                np_arr = np.frombuffer(data, dtype=np.uint8)
                frame  = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

                if frame is None:
                    print("[CLOUD] cv2.imdecode returned None — skipping")
                    continue

                h, w = frame.shape[:2]
                rgb  = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                results = hands.process(rgb)

                gesture = "Searching..."
                coords  = ""

                if results.multi_hand_landmarks:
                    for lms in results.multi_hand_landmarks:
                        detected = detect_gesture(lms.landmark)
                        if detected:
                            gesture = detected

                        # Map normalized [0..1] coords to pixel space
                        coords = ";".join(
                            f"{max(0, min(int(lm.x * w), w - 1))},"
                            f"{max(0, min(int(lm.y * h), h - 1))}"
                            for lm in lms.landmark
                        )

                payload = f"{gesture}|{coords}" if coords else f"{gesture}|NODATA"

                ws.send(payload)
                print(f"[ENGINE] Gesture={gesture} | Frame={frame_len}B")

            except Exception as proc_err:
                # Frame-level error — log it, but keep the connection alive
                print(f"[PROC] Frame processing error (non-fatal): {proc_err}")
                # Optionally send a safe fallback to avoid display freeze
                try:
                    ws.send("Searching...|NODATA")
                except Exception:
                    break  # If even send fails, connection is truly dead

    except Exception as fatal_err:
        print(f"[CLOUD] Fatal handler error: {fatal_err}")

    finally:
        # FIX [5]: Always release MediaPipe resources on disconnect.
        # Without this, leaked instances accumulate memory on Render.
        try:
            hands.close()
        except Exception:
            pass
        print("[CLOUD] Client disconnected — MediaPipe released")


# ── Launch ────────────────────────────────────────────────────
if __name__ == "__main__":
    # NOTE: For Render, use gunicorn instead of this dev server.
    # Set your Render Start Command to:
    #   gunicorn -k gevent -w 1 server:app
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
