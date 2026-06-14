# ================================================================
# RENDER CLOUD SERVER — HTTP POST FRAME UPLOAD (NO WEBSOCKET)
# ================================================================
# Receives JPEG frames via HTTP POST from ESP32
# Processes with MediaPipe and responds with gesture + coordinates
# ================================================================

import os
import cv2
import numpy as np
import mediapipe as mp
from flask import Flask, request, jsonify
import time

app = Flask(__name__)

# ── MediaPipe Setup ────────────────────────────────────────────
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
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
    return "🚀 AI Core Online", 200


# ── Frame Upload Endpoint ──────────────────────────────────────
@app.route('/upload', methods=['POST'])
def upload_frame():
    """
    Receives JPEG frame from ESP32
    Returns: "GESTURE|x1,y1;x2,y2;...x21,y21" or "GESTURE|NODATA"
    """
    try:
        # Get frame data from request body
        frame_data = request.get_data()
        
        if not frame_data or len(frame_data) < 100:
            return "Searching...|NODATA", 200
        
        # Decode JPEG
        np_arr = np.frombuffer(frame_data, dtype=np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        if frame is None:
            return "Searching...|NODATA", 200
        
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
        
        response = f"{gesture}|{coords}" if coords else f"{gesture}|NODATA"
        
        # Log occasionally
        global frame_count
        if 'frame_count' not in globals():
            frame_count = 0
        frame_count += 1
        
        if frame_count % 50 == 0:
            print(f"[→] Frame {frame_count}: Gesture={gesture}")
        
        return response, 200
    
    except Exception as e:
        print(f"[✗] Error processing frame: {e}")
        return "Searching...|NODATA", 200


# ── Launch ────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"\n[*] Starting HTTP server on port {port}...")
    print(f"[*] For Render, use: gunicorn -w 1 main:app\n")
    app.run(host="0.0.0.0", port=port, debug=False)
