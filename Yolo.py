import cv2
import time
import sys
import serial
from ultralytics import YOLO

# ======================================================================
# 1. CONFIGURACIÓN
# ======================================================================
SERIAL_PORT = 'COM5'      
BAUD_RATE = 115200
INDICE_CAMARA = 1 
WINDOW_NAME = "Smart Semaphore System v3.0" 

# TIEMPOS
SCANNING_TIME_LIMIT = 5.0 
GREEN_TIME_BASE = 15.0  
YELLOW_TIME_BASE = 5.0  

# OPTIMIZACIÓN Y YOLO
MODELO_YOLO = 'yolov8n.pt'
CLASE_PERSONA = 0
UMBRAL_CONFIANZA = 0.50
SKIP_FRAMES = 3           

# ROI (Zona de detección)
DETECTION_ZONE_VIEW = (0.2, 0.5, 0.8, 0.95)

SCANNING_POSITIONS = ["V1", "V2", "V3", "V4"]
SEMAPHORE_PINS = {
    "V1": {"R": "V1_R", "A": "V1_A", "V": "V1_V"},
    "V2": {"R": "V2_R", "A": "V2_A", "V": "V2_V"},
    "V3": {"R": "V3_R", "A": "V3_A", "V": "V3_V"},
    "V4": {"R": "V4_R", "A": "V4_A", "V": "V4_V"},
}

# ESTADO GLOBAL
exit_requested = False
traffic_counts = {v: 0 for v in SCANNING_POSITIONS}
green_history = []
current_green_via = None
current_light_state = "IDLE"
last_light_change_time = 0
frame_dims = (0, 0)

# ======================================================================
# 2. FUNCIONES DE CONTROL SERIAL (LÓGICA DE SEGURIDAD)
# ======================================================================

def send_serial_command(ser, command):
    if ser:
        try:
            ser.write((command + '\n').encode('utf-8'))
        except: pass

def update_all_semaphores(ser, active_via, active_color):
    """
    Control Total: La vía activa recibe el color (V/A), 
    todas las demás se fuerzan a ROJO_ON.
    """
    if not ser: return
    
    for via in SCANNING_POSITIONS:
        if via == active_via:
            # Seteamos la luz de la vía que tiene el turno
            for color_code in ["R", "A", "V"]:
                action = "ON" if color_code == active_color else "OFF"
                send_serial_command(ser, f"{SEMAPHORE_PINS[via][color_code]}_{action}")
        else:
            # Bloqueo de seguridad para las otras vías
            send_serial_command(ser, f"{SEMAPHORE_PINS[via]['R']}_ON")
            send_serial_command(ser, f"{SEMAPHORE_PINS[via]['A']}_OFF")
            send_serial_command(ser, f"{SEMAPHORE_PINS[via]['V']}_OFF")

# ======================================================================
# 3. FUNCIONES DE INTERFAZ Y MOUSE
# ======================================================================

def mouse_callback(event, x, y, flags, param):
    global exit_requested, frame_dims
    if event == cv2.EVENT_LBUTTONDOWN:
        w, h = frame_dims
        if x > w - 120 and y < 60:
            exit_requested = True

def draw_ui(img, fps, current_scan_via):
    h, w = img.shape[:2]
    # Panel Lateral
    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (250, h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.7, img, 0.3, 0, img)

    # Título
    cv2.putText(img, "CONTROL DE TRAFICO", (20, 40), 1, 1.2, (0, 255, 255), 2)
    
    # Lista de Vías y LEDs
    y_pos = 100
    for via in SCANNING_POSITIONS:
        if via == current_green_via:
            color = (0, 255, 0) if current_light_state == "GREEN" else (0, 255, 255)
        else:
            color = (0, 0, 255)
        
        cv2.circle(img, (35, y_pos), 10, color, -1)
        cv2.putText(img, f"{via}: {traffic_counts[via]} Pers.", (60, y_pos + 7), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        y_pos += 50

    # Status
    cv2.putText(img, f"CAMARA: {current_scan_via}", (20, h-80), 0, 0.5, (200, 200, 200), 1)
    cv2.putText(img, f"LUZ: {current_light_state}", (20, h-55), 0, 0.5, (0, 255, 255), 1)
    cv2.putText(img, f"FPS: {int(fps)}", (20, h-30), 0, 0.5, (0, 255, 0), 1)

    # Botón Salir
    cv2.rectangle(img, (w-120, 10), (w-10, 50), (0, 0, 180), -1)
    cv2.putText(img, "SALIR", (w-100, 38), 0, 0.7, (255, 255, 255), 2)

# ======================================================================
# 4. EJECUCIÓN PRINCIPAL
# ======================================================================

def run_detection():
    global exit_requested, traffic_counts, current_green_via, green_history, current_light_state, last_light_change_time, frame_dims
    
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        time.sleep(2)
    except:
        ser = None
        print("Advertencia: No se detectó ESP32 en el puerto.")

    model = YOLO(MODELO_YOLO)
    cap = cv2.VideoCapture(INDICE_CAMARA)
    
    cv2.namedWindow(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN)
    cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.setMouseCallback(WINDOW_NAME, mouse_callback)

    frame_count = 0
    scan_idx = 0
    last_scan_time = time.time()
    last_fps_time = time.time()
    fps = 0
    
    # Inicio: V1 en Verde, resto en Rojo
    current_green_via = SCANNING_POSITIONS[0] 
    current_light_state = "GREEN"
    last_light_change_time = time.time()
    update_all_semaphores(ser, current_green_via, "V")
    send_serial_command(ser, f"GIRAR_{current_green_via}")

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret or exit_requested: break
        
        frame_count += 1
        h, w = frame.shape[:2]
        frame_dims = (w, h)
        display_frame = frame.copy() 

        x_min, y_min, x_max, y_max = [int(v * s) for v, s in zip(DETECTION_ZONE_VIEW, [w, h, w, h])]
        current_scanning_via = SCANNING_POSITIONS[scan_idx]

        # 1. PROCESAMIENTO IA (Optimizado)
        if frame_count % SKIP_FRAMES == 0:
            results = model.predict(frame, conf=UMBRAL_CONFIANZA, classes=[CLASE_PERSONA], verbose=False)
            boxes = results[0].boxes.xyxy.tolist() if results[0].boxes is not None else []
            count = 0
            for box in boxes:
                x1, y1, x2, y2 = map(int, box)
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                if x_min < cx < x_max and y_min < cy < y_max:
                    count += 1
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            traffic_counts[current_scanning_via] = count

        # 2. LÓGICA DE TIEMPOS Y SEMÁFOROS
        now = time.time()
        
        # Rotación de cámara para escaneo
        if now - last_scan_time > SCANNING_TIME_LIMIT:
            scan_idx = (scan_idx + 1) % len(SCANNING_POSITIONS)
            last_scan_time = now
            send_serial_command(ser, f"GIRAR_{SCANNING_POSITIONS[scan_idx]}")

        # Cambio de Luces
        if current_light_state == "GREEN" and (now - last_light_change_time > GREEN_TIME_BASE):
            update_all_semaphores(ser, current_green_via, "A")
            current_light_state = "YELLOW"
            last_light_change_time = now

        elif current_light_state == "YELLOW" and (now - last_light_change_time > YELLOW_TIME_BASE):
            # Buscar siguiente vía con historial de exclusión
            remaining = [v for v in SCANNING_POSITIONS if v not in green_history]
            if not remaining: green_history = []; remaining = SCANNING_POSITIONS
            
            current_green_via = max(remaining, key=lambda v: traffic_counts[v])
            green_history.append(current_green_via)
            
            update_all_semaphores(ser, current_green_via, "V")
            send_serial_command(ser, f"GIRAR_{current_green_via}")
            
            current_light_state = "GREEN"
            last_light_change_time = now

        # 3. DIBUJAR INTERFAZ
        cv2.rectangle(display_frame, (x_min, y_min), (x_max, y_max), (255, 255, 0), 1)
        if frame_count % 10 == 0:
            fps = 10 / (time.time() - last_fps_time)
            last_fps_time = time.time()
        
        draw_ui(display_frame, fps, current_scanning_via)

        cv2.imshow(WINDOW_NAME, display_frame)
        if cv2.waitKey(1) & 0xFF == ord('q'): break

    cap.release()
    cv2.destroyAllWindows()
    if ser: ser.close()

if __name__ == "__main__":
    run_detection()