# ================================================================
# Semáforo inteligente ESP32 (MicroPython) - Relés + Torre de 2 Servos
# ================================================================
# - Control exclusivo de luces por vía (R, A, V)
# - Giro de cámara a V1/V2/V3/V4 vía comandos GIRAR_Vx
# - Dos servos en torre:
#       Servo BASE (GPIO13): frontal y trasera
#       Servo TOP  (GPIO12): derecha e izquierda
# - Entrada por USB CDC (sys.stdin): Vx_R_ON / Vx_A_OFF / GIRAR_Vx
# ================================================================

from machine import Pin, PWM
import time
import sys

# ================================================================
# CONFIGURACIÓN GENERAL
# ================================================================

# Si tu módulo de relés es activo en LOW, cambia a True
# True  -> relés activos en LOW (0 = ON, 1 = OFF)
# False -> relés activos en HIGH (1 = ON, 0 = OFF)
RELAY_ACTIVE_LOW = False

# Servos
PIN_SERVO_BASE = 13   # Servo abajo
PIN_SERVO_TOP  = 12   # Servo arriba
SERVO_FREQ = 50       # Hz

# Pines de relés por vía y color
RELAY_PINS = {
    "V1_R": 15, "V1_A": 2,  "V1_V": 4,
    "V2_R": 16, "V2_A": 17, "V2_V": 5,
    "V3_R": 18, "V3_A": 19, "V3_V": 21,
    "V4_R": 22, "V4_A": 23, "V4_V": 32
}

# Ángulos de cámara por vía (torre de dos servos)
POSICIONES_CAMARA = {
    "V1": ("BASE", 0),     # Frontal
    "V2": ("BASE", 180),   # Trasera
    "V3": ("TOP", 90),     # Derecha
    "V4": ("TOP", 180)     # Izquierda
}

# ================================================================
# ESTADO / OBJETOS
# ================================================================

relay_objects = {}
servo_base = None
servo_top = None

# ================================================================
# FUNCIONES DE SERVO
# ================================================================

def angle_to_duty(angle):
    """
    Convierte un ángulo (0–180) a duty_u16 para PWM 50 Hz.
    MG995 típico: ~0.5 ms (0°) a ~2.4 ms (180°).
    Periodo = 20 ms -> duty_u16 = (pulso_us / 20000) * 65535
    """
    if angle < 0:
        angle = 0
    if angle > 180:
        angle = 180
    us = 500 + int((2400 - 500) * angle / 180)
    duty_u16 = int(us * 65535 / 20000)
    print(f"[ESP32] Calculado duty={duty_u16} para angle={angle}")
    return max(2000, min(8000, duty_u16))

def set_servo_angle(servo_pwm, angle, settle_ms=750):
    """
    Mueve un servo al ángulo indicado y espera settle_ms para estabilizar.
    """
    if not servo_pwm:
        print("[ESP32] Error: servo_pwm no inicializado")
        return
    duty = angle_to_duty(angle)
    try:
        servo_pwm.duty_u16(duty)
        print(f"[ESP32] Servo movido a angle={angle}, duty={duty}")
    except Exception as e:
        print(f"[ESP32] PWM error: {e}")
        return
    time.sleep_ms(settle_ms)

def girar_a_via(via_key):
    """
    Gira la cámara a la vía indicada usando el servo correspondiente.
    """
    if via_key in POSICIONES_CAMARA:
        servo_id, angle = POSICIONES_CAMARA[via_key]
        if servo_id == "BASE":
            set_servo_angle(servo_base, angle)
        elif servo_id == "TOP":
            set_servo_angle(servo_top, angle)
        print(f"[ESP32] CÁMARA -> {via_key} ({servo_id}={angle}°)")
        return True
    print(f"[ESP32] CÁMARA: vía desconocida {via_key}")
    return False

# ================================================================
# FUNCIONES DE RELÉS / LUCES
# ================================================================

def set_light(key, state):
    """
    Controla una luz individual del semáforo.
    state: 1 (ON) o 0 (OFF).
    Respeta RELAY_ACTIVE_LOW:
      - Si True:  ON -> 0, OFF -> 1
      - Si False: ON -> 1, OFF -> 0
    """
    if key not in relay_objects:
        print(f"[ESP32] set_light: clave desconocida {key}")
        return

    if state == 1:  # ON
        pin_value = 0 if RELAY_ACTIVE_LOW else 1
        relay_objects[key].value(pin_value)
        print(f"[ESP32] LUZ ON  -> {key} (pin={pin_value})")
    else:           # OFF
        pin_value = 1 if RELAY_ACTIVE_LOW else 0
        relay_objects[key].value(pin_value)
        print(f"[ESP32] LUZ OFF -> {key} (pin={pin_value})")

def set_via_state(via, color):
    """
    Exclusividad: enciende solo el color indicado de la vía (R, A, V)
    y apaga los otros dos.
    """
    for c in ["R", "A", "V"]:
        full_key = f"{via}_{c}"
        if c == color:
            set_light(full_key, 1)  # ON
        else:
            set_light(full_key, 0)  # OFF

# ================================================================
# INICIALIZACIÓN DE HARDWARE
# ================================================================

def initialize_hardware():
    global servo_base, servo_top
    # Inicializar relés y dejarlos en OFF
    off_value = 1 if RELAY_ACTIVE_LOW else 0
    for key, pin_num in RELAY_PINS.items():
        p = Pin(pin_num, Pin.OUT)
        p.value(off_value)
        relay_objects[key] = p
        print(f"[ESP32] Relay {key} inicializado en pin {pin_num}, OFF={off_value}")

    # Inicializar servos
    try:
        servo_base = PWM(Pin(PIN_SERVO_BASE), freq=SERVO_FREQ)
        servo_top  = PWM(Pin(PIN_SERVO_TOP), freq=SERVO_FREQ)
        girar_a_via("V1")  # posición inicial frontal
    except Exception as e:
        print(f"[ESP32] ERROR servo: {e}")

    print("[ESP32] Hardware inicializado. Esperando comandos...")

# ================================================================
# COMANDOS (USB CDC via sys.stdin)
# ================================================================

def handle_command(command):
    cmd = command.strip().upper()
    if not cmd:
        return
    print(f"[ESP32] RX: '{cmd}'")

    # Giro: GIRAR_Vx
    if cmd.startswith("GIRAR_"):
        via_key = cmd.split('_')[1]
        girar_a_via(via_key)
        return

    # Luces: Vx_R_ON / Vx_V_OFF / etc.
    parts = cmd.split('_')
    if len(parts) == 3 and parts[0].startswith('V'):
        via = parts[0]      # V1, V2, V3, V4
        color = parts[1]    # R, A, V
        action = parts[2]   # ON, OFF
        if action == "ON":
            set_via_state(via, color)
        elif action == "OFF":
            set_light(f"{via}_{color}", 0)
        return

    print(f"[ESP32] Comando no reconocido: '{cmd}'")

# ================================================================
# BUCLE PRINCIPAL
# ================================================================

def main_loop():
    initialize_hardware()
    while True:
        try:
            line = sys.stdin.readline()
            if line:
                handle_command(line)
        except Exception as e:
            print(f"[ESP32] Error lectura: {e}")
            time.sleep(0.2)

# ================================================================
# ENTRY POINT
# ================================================================

if __name__ == "__main__":
    main_loop()

