import asyncio
import websockets
import cv2
import numpy as np
import mediapipe as mp
import time
import http
from websockets.server import WebSocketServerProtocol

# ── MEDIAPIPE INITIALIZATION ─────────────────────────────────────
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    model_complexity=0, 
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

# ── 🤖 CUSTOM PROTOCOL TO SILENTLY HANDLE RENDER PINGS ───────────
class HealthCheckServerProtocol(WebSocketServerProtocol):
    async def process_request(self, path, request_headers):
        # Intercept Render's Health Check Scanner BEFORE the websocket handshake fails
        return http.HTTPStatus.OK, [("Content-Type", "text/plain")], b"AI Core Online\n"

# ── UNIFIED CLOUD PROCESSING LOOP ─────────────────────────────────
async def handle_esp32_client(websocket):
    print(f"[CLOUD] ESP32-CAM Client connected via secure cloud port tunnel!")
    last_mp_time = 0
    MP_INTERVAL = 0.03 

    try:
        async for message in websocket:
            if isinstance(message, str):
                continue

            # Process Incoming JPEG Stream
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
                    
                    await websocket.send(payload)

    except websockets.exceptions.ConnectionClosed:
        print("[CLOUD] ESP32 client disconnected cleanly.")
    except Exception as e:
        print(f"[SYSTEM ERROR] Engine loop exception: {e}")

# ── 🚀 RUN TIME ENTRYPOINT ───────────────────────────────────────
async def main():
    # Use our custom protocol class to process incoming web packets safely
    async with websockets.serve(
        handle_esp32_client, 
        "0.0.0.0", 
        10000, 
        create_protocol=HealthCheckServerProtocol
    ):
        print("[BOOT] Unified Cloud WebSocket Processing Core Online on Port 10000...")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
