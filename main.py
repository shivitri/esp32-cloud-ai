import asyncio
import websockets
import cv2
import numpy as np
import mediapipe as mp
import time

# ── MEDIAPIPE INITIALIZATION ─────────────────────────────────────
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    model_complexity=0, # Performance optimized for cloud CPU
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

# ── UNIFIED CLOUD ENGINE ──────────────────────────────────────────
async def handle_esp32_client(websocket):
    print(f"[CLOUD] ESP32-CAM Client connected via secure cloud port tunnel!")
    last_mp_time = 0
    MP_INTERVAL = 0.03 # Throttle to protect CPU frame timing

    try:
        async for message in websocket:
            # Render health checks send text strings, the camera sends binary JPEG bytes
            if isinstance(message, str):
                if message == "PING":
                    await websocket.send("PONG")
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

                    # Build unified transmission packet
                    payload = f"{current_gesture}|{coord_string}" if coord_string else f"{current_gesture}|NODATA"
                    print(f"[ENGINE] Target Signature: {current_gesture}")
                    
                    # Echo calculations straight back up the pipeline websocket channel
                    await websocket.send(payload)

    except websockets.exceptions.ConnectionClosed:
        print("[CLOUD] ESP32 client disconnected cleanly.")
    except Exception as e:
        print(f"[SYSTEM ERROR] Engine loop exception: {e}")

async def main():
    # Render reads port 10000 natively for web apps
    async with websockets.serve(handle_esp32_client, "0.0.0.0", 10000):
        print("[BOOT] Unified Cloud WebSocket Processing Core Online on Port 10000...")
        await asyncio.Future() # keep server running forever

if __name__ == "__main__":
    asyncio.run(main())
