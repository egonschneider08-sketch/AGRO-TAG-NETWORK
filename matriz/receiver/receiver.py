"""
Agro sustain Network — Raspberry Pi LoRa Receiver
=============================================
Recebe pacotes LoRa do nó mestre ESP32, desempacota a struct SensorData
e salva em banco SQLite local.

Compatível com: Raspberry Pi 3 + Ubuntu + SX1276 (Ra-02 / RFM95)
Dependências:   pip install RPi.GPIO spidev

NÃO usa pyLoRa — acessa o chip diretamente via spidev (mais confiável).

Pinagem padrão (Raspberry Pi → Ra-02 / RFM95):
    3.3V     (Pin 1)  → VCC
    GND      (Pin 6)  → GND
    GPIO10   (Pin 19) → MOSI
    GPIO9    (Pin 21) → MISO
    GPIO11   (Pin 23) → SCK
    GPIO8    (Pin 24) → NSS/CS   ← controlado pelo spidev (CE0)
    GPIO22   (Pin 15) → RST
    GPIO25   (Pin 22) → DIO0
"""

import struct
import time
import sqlite3
import logging
import signal
import sys
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

from sx1276 import SX1276

# ============================================================
# CONFIGURAÇÃO — deve ser igual ao config.h do ESP32
# ============================================================
LORA_FREQUENCY  = 915       # MHz  (915 = Américas, 868 = Europa, 433 = Ásia)
LORA_SF         = 12        # Spreading Factor
LORA_BW         = 125000    # Bandwidth Hz
LORA_CR         = 8         # Coding Rate (4/8)

PIN_RST         = 22        # GPIO BCM
PIN_DIO0        = 25        # GPIO BCM

DB_PATH         = "agrotag.db"
POLL_INTERVAL_S = 0.05      # 50ms entre verificações

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("receiver.log"),
    ]
)
log = logging.getLogger("agrotag")

# ============================================================
# STRUCT — idêntica ao data_types.h do ESP32
#
# #pragma pack(push, 1)
# struct SensorData {
#     uint8_t  node_id;           // 1 byte
#     float    soil_moisture;     // 4 bytes
#     float    soil_temperature;  // 4 bytes
#     float    air_humidity;      // 4 bytes
#     float    ec;                // 4 bytes
#     float    ph;                // 4 bytes
#     float    nitrogen;          // 4 bytes
#     float    phosphorus;        // 4 bytes
#     float    potassium;         // 4 bytes
#     uint32_t timestamp_ms;      // 4 bytes
# };                              // total: 37 bytes
# #pragma pack(pop)
# ============================================================
SENSOR_FMT  = "<BffffffffI"
SENSOR_SIZE = struct.calcsize(SENSOR_FMT)  # deve ser 37 bytes


@dataclass
class SensorData:
    node_id:          int
    soil_moisture:    float
    soil_temperature: float
    air_humidity:     float
    ec:               float
    ph:               float
    nitrogen:         float
    phosphorus:       float
    potassium:        float
    timestamp_ms:     int
    received_at:      str = field(default_factory=lambda: datetime.now().isoformat())

    def __str__(self):
        return (
            f"Nó {self.node_id} | "
            f"Umidade={self.soil_moisture:.1f}% | "
            f"Temp={self.soil_temperature:.1f}°C | "
            f"pH={self.ph:.2f} | "
            f"EC={self.ec:.1f}µS/cm | "
            f"N={self.nitrogen:.1f} P={self.phosphorus:.1f} K={self.potassium:.1f} mg/kg"
        )


# ============================================================
# DESEMPACOTAMENTO
# ============================================================

def unpack_sensor(raw: bytes) -> Optional[SensorData]:
    """Desempacota 37 bytes na struct SensorData."""
    if len(raw) != SENSOR_SIZE:
        log.warning(f"Tamanho inesperado: {len(raw)} bytes (esperado {SENSOR_SIZE})")
        return None
    try:
        fields = struct.unpack(SENSOR_FMT, raw)
        node_id = fields[0]
        if not (1 <= node_id <= 5):
            log.warning(f"node_id inválido: {node_id} — pacote descartado")
            return None
        return SensorData(*fields)
    except struct.error as e:
        log.error(f"Erro ao desempacotar struct: {e}")
        return None


def unpack_multi(raw: bytes) -> list[SensorData]:
    """
    Desempacota pacote com múltiplos sensores.
    Formato enviado pelo mestre: [count: 1 byte][SensorData × count]
    """
    if len(raw) < 1:
        log.warning("Pacote vazio recebido")
        return []

    count   = raw[0]
    payload = raw[1:]

    if count == 0 or count > 5:
        log.warning(f"count inválido: {count}")
        return []

    expected_size = count * SENSOR_SIZE
    if len(payload) != expected_size:
        log.warning(
            f"Payload com tamanho errado: {len(payload)} bytes "
            f"para {count} sensores (esperado {expected_size})"
        )
        return []

    sensors = []
    for i in range(count):
        chunk = payload[i * SENSOR_SIZE:(i + 1) * SENSOR_SIZE]
        s = unpack_sensor(chunk)
        if s:
            sensors.append(s)

    return sensors


# ============================================================
# BANCO DE DADOS SQLite
# ============================================================

def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("""
                 CREATE TABLE IF NOT EXISTS sensor_readings (
                                                                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                                                                received_at      TEXT    NOT NULL,
                                                                node_id          INTEGER NOT NULL,
                                                                soil_moisture    REAL,
                                                                soil_temperature REAL,
                                                                air_humidity     REAL,
                                                                ec               REAL,
                                                                ph               REAL,
                                                                nitrogen         REAL,
                                                                phosphorus       REAL,
                                                                potassium        REAL,
                                                                timestamp_ms     INTEGER,
                                                                rssi             INTEGER,
                                                                snr              REAL
                 )
                 """)
    conn.execute("""
                 CREATE INDEX IF NOT EXISTS idx_node_time
                     ON sensor_readings (node_id, received_at)
                 """)
    conn.commit()
    log.info(f"Banco de dados pronto: {path}")
    return conn


def save(conn: sqlite3.Connection, s: SensorData, rssi: int, snr: float):
    conn.execute("""
                 INSERT INTO sensor_readings (
                     received_at, node_id,
                     soil_moisture, soil_temperature, air_humidity,
                     ec, ph, nitrogen, phosphorus, potassium,
                     timestamp_ms, rssi, snr
                 ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                 """, (
                     s.received_at, s.node_id,
                     s.soil_moisture, s.soil_temperature, s.air_humidity,
                     s.ec, s.ph, s.nitrogen, s.phosphorus, s.potassium,
                     s.timestamp_ms, rssi, snr
                 ))
    conn.commit()


# ============================================================
# LOOP PRINCIPAL
# ============================================================

def receive_loop(lora: SX1276, conn: sqlite3.Connection):
    lora.start_rx()
    log.info("Aguardando pacotes LoRa...\n")

    running = True

    def handle_exit(sig, frame):
        nonlocal running
        log.info("Sinal de encerramento recebido...")
        running = False

    signal.signal(signal.SIGINT,  handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    while running:
        try:
            if lora.packet_available():
                payload, rssi, snr = lora.read_packet()

                if not payload:
                    log.warning("Pacote com CRC error — descartado")
                    lora.start_rx()
                    continue

                log.info(
                    f"Pacote recebido: {len(payload)} bytes | "
                    f"RSSI={rssi} dBm | SNR={snr:.1f} dB"
                )

                sensors = unpack_multi(payload)

                if not sensors:
                    log.warning("Nenhum sensor válido no pacote")
                else:
                    for s in sensors:
                        log.info(f"  ✅ {s}")
                        save(conn, s, rssi, snr)
                    log.info(f"  💾 {len(sensors)} registro(s) salvos no banco\n")

                lora.start_rx()

        except Exception as e:
            log.error(f"Erro no loop: {e}", exc_info=True)
            time.sleep(1)
            lora.start_rx()

        time.sleep(POLL_INTERVAL_S)

    lora.close()
    log.info("Receptor encerrado.")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    assert SENSOR_SIZE == 37, (
        f"ERRO: struct tem {SENSOR_SIZE} bytes, esperado 37. "
        f"Verifique SENSOR_FMT."
    )

    log.info("=" * 55)
    log.info("  AgroTag Network — Receptor LoRa")
    log.info(f"  Frequência: {LORA_FREQUENCY} MHz | SF{LORA_SF} | BW{LORA_BW//1000}kHz")
    log.info(f"  Struct SensorData: {SENSOR_SIZE} bytes")
    log.info("=" * 55)

    lora = SX1276(pin_rst=PIN_RST, pin_dio0=PIN_DIO0)

    if not lora.begin(LORA_FREQUENCY, sf=LORA_SF, bw=LORA_BW, cr=LORA_CR):
        log.error("Falha ao inicializar o módulo LoRa. Verifique a pinagem e alimentação.")
        sys.exit(1)

    conn = init_db(DB_PATH)

    try:
        receive_loop(lora, conn)
    finally:
        conn.close()