"""
================================================================
 CLOUD-NATIVE MAIN ENGINE — INTEGRATED SCANNED WORKAROUND
================================================================
"""
import os
import cv2
import numpy as np
import mediapipe as mp
import socket
import threading
import time
import struct
import http.server
import socketserver
from collections import deque

# ── 🛠️ 1. DUMMY WEB SERVER WORKAROUND FOR RENDER FREE TIER ──────
def run_dummy_web_server():
    PORT = 10000  # Render looks at port 10000 by default for Python services
    Handler = http.server.SimpleHTTPRequestHandler
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("", PORT), Handler) as httpd:
            print(f"[Web Server] Listening on port {PORT} for Render health checks...")
            httpd.serve_forever()
    except Exception as e:
        print(f"[Web Server Error] Could not start port 10000 dummy listener: {e}")

# Instantly spin up the dummy web server thread so Render stays green
web_thread = threading.Thread(target=run_dummy_web_server, daemon=True)
web_thread.start()


# ── ☁️ BINDING CONFIGURATION FOR CLOUD NETWORKING ────────────────
ESP32_IP     = "0.0.0.0" 
STREAM_PORT  = 81
GESTURE_PORT = 82

latest_frame  = deque(maxlen=1)   
gesture_queue = deque(maxlen=2)   


# ── MEDIAPIPE CORE INITIALIZATION ────────────────────────────────
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode        = False,
    max_num_hands            = 1,
    model_complexity         = 0,     # 0 = Best performance for cloud CPU tiers
    min_detection_confidence = 0.5,
    min_tracking_confidence  = 0.5,
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
    return ""


# ================================================================
#  THREAD 1 — Background Stream Reader (Server Listener Mode)
# ================================================================
def tcp_stream_reader():
    while True:
        try:
            server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_sock.bind((ESP32_IP, STREAM_PORT))
            server_sock.listen(1)
            print(f"[Cloud Engine] Video Stream Channel open on port {STREAM_PORT}...")
            
            conn, addr = server_sock.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"[Cloud Engine] Video stream connected from: {addr}")
            
            while True:
                header = b""
                while len(header) < 4:
                    chunk = conn.recv(4 - len(header))
                    if not chunk: raise OSError()
                    header += chunk
                frame_size = struct.unpack("<I", header)[0]
                frame_data = b""
                while len(frame_data) < frame_size:
                    chunk = conn.recv(min(frame_size - len(frame_data), 16384))
                    if not chunk: raise OSError()
                    frame_data += chunk
                np_arr = np.frombuffer(frame_data, dtype=np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if frame is not None: latest_frame.append(frame)
        except Exception as e:
            print(f"[Stream Warning] Re-initializing socket due to: {e}")
            latest_frame.clear()
            time.sleep(1.0)


# ================================================================
#  THREAD 2 — Background Signal Channel (Server Listener Mode)
# ================================================================
def gesture_sender():
    while True:
        try:
            server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_sock.bind((ESP32_IP, GESTURE_PORT))
            server_sock.listen(1)
            print(f"[Cloud Engine] Data Sync Channel open on port {GESTURE_PORT}...")
            
            conn, addr = server_sock.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"[Cloud Engine] Data pipeline connected from: {addr}")
            
            while True:
                if not gesture_queue:
                    time.sleep(0.005)
                    continue
                payload = gesture_queue.pop()
                try:
                    conn.sendall((payload + "\n").encode())
                except OSError:
                    break
        except Exception as e:
            print(f"[Data Warning] Re-initializing socket due to: {e}")
            time.sleep(1.0)


# Run background network daemons immediately
threading.Thread(target=tcp_stream_reader, daemon=True).start()
threading.Thread(target=gesture_sender, daemon=True).start()


# ================================================================
#  MAIN COMPUTATION RUNTIME
# ================================================================
last_payload  = ""
last_mp_time  = 0.0
MP_INTERVAL   = 0.02  
fps_count, fps_timer, fps_display = 0, time.time(), 0

print("[System Initialization] Cloud AI Processing Core active...")

while True:
    if not latest_frame:
        time.sleep(0.001)
        continue

    raw_img = latest_frame[-1].copy()
    h_max, w_max, _ = raw_img.shape 
    now = time.time()

    current_gesture = "Searching..."
    coord_string = ""

    if now - last_mp_time >= MP_INTERVAL:
        last_mp_time = now
        rgb = cv2.cvtColor(raw_img, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

        if results.multi_hand_landmarks:
            for lms in results.multi_hand_landmarks:
                detected = detect_gesture(lms.landmark)
                if detected: current_gesture = detected
                
                coord_list = []
                for lm in lms.landmark:
                    cx = int(lm.x * w_max)
                    cy = int(lm.y * h_max)
                    cx = max(0, min(cx, 159))
                    cy = max(0, min(cy, 119))
                    coord_list.append(f"{cx},{cy}")
                
                coord_string = ";".join(coord_list)

        if coord_string:
            payload_packet = f"{current_gesture}|{coord_string}"
        else:
            payload_packet = "NODATA"

        if payload_packet != last_payload:
            gesture_queue.append(payload_packet)
            last_payload = payload_packet

    fps_count += 1
    if now - fps_timer >= 1.0:
        fps_display, fps_count, fps_timer = fps_count, 0, now
        print(f"[LIVE LOG] FPS: {fps_display} | Pipeline Sign: {current_gesture}")
