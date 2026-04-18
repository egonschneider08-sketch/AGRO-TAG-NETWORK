# 🌱 Agro sustain Network

> Rede de sensores agrícolas sem fio baseada em ESP32, com comunicação ESP-NOW e transmissão LoRa para monitoramento em tempo real de solo e ambiente.

---

## 📡 Visão Geral

O **Agro sustain Network** é um sistema embarcado distribuído para monitoramento agrícola de precisão. Quatro nós sensores ESP32 coletam dados de solo via protocolo Modbus RS485 e os transmitem sem fio até um nó mestre via **ESP-NOW**, que consolida as informações e as envia por **LoRa** para uma Raspberry Pi ou gateway central — tudo isso **sem necessidade de Wi-Fi ou internet**.

```
[Nó 1] ──ESP-NOW──▶ [Nó 2] ──ESP-NOW──▶ [Nó 3] ──ESP-NOW──▶ [Nó 4] ──ESP-NOW──▶ [Mestre] ──LoRa──▶ [Raspberry Pi]
   │                   │                   │                   │
[Sensor]           [Sensor]           [Sensor]           [Sensor]
Modbus RS485       Modbus RS485       Modbus RS485       Modbus RS485
```

---

## 📊 Dados Coletados

Cada nó sensor coleta os seguintes parâmetros via sensor Modbus RS485 (NPK + pH + ambiente):

| Parâmetro           | Unidade  |
|---------------------|----------|
| Umidade do solo     | %        |
| Temperatura do solo | °C       |
| Umidade do ar       | %        |
| Condutividade elétrica (EC) | µS/cm |
| pH                  | —        |
| Nitrogênio (N)      | mg/kg    |
| Fósforo (P)         | mg/kg    |
| Potássio (K)        | mg/kg    |

---

## 🗂️ Estrutura do Projeto

```
agro sustain-network/
│
├── common/                    # Código compartilhado entre todos os nós
│   ├── data_types.h           # Struct SensorData (com static_assert de tamanho)
│   ├── esp_now_manager.h/.cpp # Abstração ESP-NOW (peer, send, callbacks)
│   └── sensor_modbus.h/.cpp   # Driver Modbus RS485 para sensor NPK/pH
│
├── node_slave/                # Firmware dos nós escravos (1 a 4)
│   ├── config.h               # NODE_ID, SEND_OFFSET_MS, NEXT_MAC, pinos
│   └── main.cpp               # Leitura Modbus + encaminhamento ESP-NOW
│
└── esp_manager/               # Firmware do nó mestre (nó 5)
    ├── config.h               # Pinos LoRa, intervalo de envio, MACs
    ├── lora_sender.h/.cpp     # Driver LoRa (SX1276 / Ra-02)
    └── main.cpp               # Recepção ESP-NOW + envio LoRa
```

---

## 🔧 Hardware Necessário

### Por nó escravo (×4)
| Componente | Descrição |
|---|---|
| ESP32 DevKit | Qualquer variante com Wi-Fi (para ESP-NOW) |
| Sensor NPK + pH + EC | Interface RS485 Modbus RTU |
| Módulo MAX485 | Conversor TTL ↔ RS485 |

### Nó mestre (×1)
| Componente | Descrição |
|---|---|
| ESP32 DevKit | Com pinos SPI disponíveis |
| Módulo LoRa SX1276 | Ex: Ra-02, HopeRF RFM95 |
| Raspberry Pi (ou gateway) | Receptor LoRa para processamento central |

### Pinagem padrão — Nó Mestre (LoRa)
| Sinal | Pino ESP32 |
|---|---|
| SS (NSS/CS) | GPIO 5 |
| RST | GPIO 14 |
| DIO0 | GPIO 2 |

### Pinagem padrão — Nó Escravo (RS485)
| Sinal | Pino ESP32 |
|---|---|
| DE / RE | GPIO 4 |
| TX (para MAX485) | Serial2 TX |
| RX (do MAX485) | Serial2 RX |

---

## ⚙️ Configuração

### Nós Escravos

Edite `node_slave/config.h` com os valores específicos de cada nó:

```cpp
#define NODE_ID          1        // 1, 2, 3 ou 4
#define SEND_OFFSET_MS   0UL      // Offset para evitar colisão (ver tabela)
#define NEXT_MAC         {0x24, 0x6F, 0x28, 0xBB, 0xBB, 0x02}  // MAC do próximo nó
```

**Tabela de configuração por nó:**

| Nó | `NODE_ID` | `SEND_OFFSET_MS` | `NEXT_MAC`       |
|----|-----------|------------------|------------------|
| 1  | `1`       | `0`              | MAC do Nó 2      |
| 2  | `2`       | `750`            | MAC do Nó 3      |
| 3  | `3`       | `1500`           | MAC do Nó 4      |
| 4  | `4`       | `2250`           | MAC do Mestre    |

> 💡 O offset escalonado evita colisões no ESP-NOW quando múltiplos nós transmitem no mesmo intervalo.

### Nó Mestre

Edite `esp_manager/config.h`:

```cpp
#define NODE_1_MAC  {0x24, 0x6F, 0x28, 0xAA, 0xAA, 0x01}
#define NODE_2_MAC  {0x24, 0x6F, 0x28, 0xBB, 0xBB, 0x02}
#define NODE_3_MAC  {0x24, 0x6F, 0x28, 0xCC, 0xCC, 0x03}
#define NODE_4_MAC  {0x24, 0x6F, 0x28, 0xDD, 0xDD, 0x04}

#define LORA_FREQUENCY   915E6   // 915 MHz (Américas)
```

> ⚠️ Para descobrir o MAC de cada ESP32, suba o firmware com `DEBUG_ENABLE 1` e leia o Serial Monitor na inicialização.

---

## 🚀 Build e Upload (PlatformIO)

### Dependências

As bibliotecas `esp_now` e `WiFi` já estão incluídas no framework ESP32 e **não precisam** ser declaradas manualmente.

**`platformio.ini` — Nó Escravo:**
```ini
[env:node_slave]
platform = espressif32
board = esp32dev
framework = arduino

lib_deps =
    4-20ma/ModbusMaster @ ^2.0.1

monitor_speed = 115200
upload_speed = 921600
```

**`platformio.ini` — Nó Mestre:**
```ini
[env:node_master]
platform = espressif32
board = esp32dev
framework = arduino

lib_deps =
    sandeepmistry/LoRa @ ^0.8.0

monitor_speed = 115200
upload_speed = 921600
```

### Upload

```bash
# Selecione o ambiente e faça upload
pio run -e node_slave --target upload
pio run -e node_master --target upload

# Monitor serial
pio device monitor
```

---

## 📡 Protocolo de Comunicação

### ESP-NOW (Nó → Mestre)
- **Modo:** `WIFI_STA` sem associação a roteador
- **Payload:** struct `SensorData` (37 bytes, packed)
- **Topologia:** cadeia linear com encaminhamento entre nós
- **Limite:** até 250 bytes por pacote (ESP-NOW)

### LoRa (Mestre → Gateway)
- **Chip:** SX1276 (Ra-02 / RFM95)
- **Frequência:** 915 MHz (configurável para 868/433 MHz)
- **Spreading Factor:** SF12 (máximo alcance)
- **Bandwidth:** 125 kHz
- **Coding Rate:** CR4/8
- **TX Power:** 20 dBm
- **Formato do pacote:** `[count: 1 byte][SensorData × N]`

---

## 🛡️ Decisões de Robustez

- **`static_assert`** garante em tempo de compilação que `SensorData` cabe no limite ESP-NOW
- **`memcpy`** usado no lugar de cast direto para garantir alinhamento de memória
- **Fila de encaminhamento** no callback ESP-NOW evita chamadas reentrantes ao SDK
- **Offset de envio** escalonado por nó previne colisões simultâneas
- **Verificação de `node_id`** antes de encaminhar descarta pacotes corrompidos
- **`esp_read_mac()`** substitui `WiFi.macAddress()` depreciado no ESP32 Arduino Core 2.x
- **`yield()`** no loop principal em vez de `delay(10)` para não bloquear callbacks

---

## 📝 Licença

Este projeto é open-source. Consulte o arquivo `LICENSE` para mais informações.
