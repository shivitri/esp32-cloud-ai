# ================================================================
# RENDER CLOUD SERVER — ULTRA-LIGHTWEIGHT (MINIMAL MEMORY)
# ================================================================
# This version uses minimal resources to prevent worker timeouts
# ================================================================

import os
import cv2
import numpy as np
import mediapipe as mp
from flask import Flask, request

app = Flask(__name__)

# ── Single Global MediaPipe Instance (reuse, don't recreate) ──
hands = mp.solutions.hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    model_complexity=0,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

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
    return "OK", 200


# ── Frame Upload Endpoint ──────────────────────────────────────
@app.route('/upload', methods=['POST'])
def upload_frame():
    try:
        frame_data = request.get_data()
        
        if not frame_data or len(frame_data) < 100 or len(frame_data) > 20000:
            return "Searching...|NODATA", 200
        
        # Decode JPEG quickly
        np_arr = np.frombuffer(frame_data, dtype=np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        if frame is None:
            return "Searching...|NODATA", 200
        
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Run MediaPipe (single instance, reused)
        results = hands.process(rgb)
        
        gesture = "Searching..."
        coords = ""
        
        if results.multi_hand_landmarks:
            for lms in results.multi_hand_landmarks:
                detected = detect_gesture(lms.landmark)
                if detected:
                    gesture = detected
                
                # Build coordinate string
                coord_list = []
                for lm in lms.landmark:
                    px = max(0, min(int(lm.x * w), w - 1))
                    py = max(0, min(int(lm.y * h), h - 1))
                    coord_list.append(f"{px},{py}")
                coords = ";".join(coord_list)
        
        response = f"{gesture}|{coords}" if coords else f"{gesture}|NODATA"
        return response, 200
    
    except:
        return "Searching...|NODATA", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
