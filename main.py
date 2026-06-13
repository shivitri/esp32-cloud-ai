import os
import cv2
import numpy as np
import mediapipe as mp
import time
from flask import Flask
from flask_sock import Sock

# ── INITIALIZE FLASK & WEBSOCKET ENGINE ───────────────────────────
app = Flask(__name__)
sock = Sock(app)

# ── MEDIAPIPE INITIALIZATION ─────────────────────────────────────
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    model_complexity=0, # Optimized for cloud execution
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

def detect_gesture(landmarks):
    tip_ids = [4, 8, 12, 16, 20]
    fingers = []
    if landmarks[tip_ids[0]].x < landmarks[tip_ids[0] - 1].x: fingers.append(1)
    else: fingers.append(0)
    for i in range(1, 5):
        if landmarks[tip_ids[i]].y < landmarks[tip_ids[i] - 2].y: fingers.append(1)
        else: fingers.append(0)

    total_fingers = sum(fingers)
    if total_fingers == 5: return "HELLO"
    elif total_fingers == 0: return "EMERGENCY"  
    elif total_fingers == 2: return "YES"
    elif total_fingers == 1: return "WATER"      
    elif total_fingers == 3: return "FOOD"       
    elif total_fingers == 4: return "MEDICINE"   
    elif fingers == [1, 0, 0, 0, 0]: return "REST"       
    return "Searching..."

# ── 🌐 RENDER HEALTH CHECK ROUTE ──────────────────────────────────
@app.route('/')
@app.route('/healthz')
def health_check():
    # Automatically answers GET/HEAD requests to keep Render completely green
    return "AI Core Online", 200

# ── 🔌 ESP32-CAM STREAMING ROUTE ──────────────────────────────────
@sock.route('/')
def handle_esp32_client(ws):
    print("[CLOUD] ESP32-CAM Client linked via secure WebSocket route!")
    last_mp_time = 0
    MP_INTERVAL = 0.03 # Throttled processing cycle

    while True:
        try:
            message = ws.receive()
            if not message:
                continue

            # Process incoming frame buffer bytes
            now = time.time()
            if now - last_mp_time >= MP_INTERVAL:
                last_mp_time = now
                np_arr = np.frombuffer(message, dtype=np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

                if frame is not None:
                    h_max, w_max, _ = frame.shape
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = hands.process(rgb)
                    
                    current_gesture = "Searching..."
                    coord_string = ""

                    if results.multi_hand_landmarks:
                        for lms in results.multi_hand_landmarks:
                            detected = detect_gesture(lms.landmark)
                            if detected: current_gesture = detected
                            
                            coord_list = [f"{max(0, min(int(lm.x * w_max), 159))},{max(0, min(int(lm.y * h_max), 119))}" for lm in lms.landmark]
                            coord_string = ";".join(coord_list)

                    payload = f"{current_gesture}|{coord_string}" if coord_string else f"{current_gesture}|NODATA"
                    print(f"[ENGINE] Target Signature: {current_gesture}")
                    
                    ws.send(payload)

        except Exception as e:
            print(f"[DISCONNECT] Client connection dropped: {e}")
            break

# ── 🚀 LAUNCH ENGINE ─────────────────────────────────────────────
if __name__ == "__main__":
    # Render binds automatically to port 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
