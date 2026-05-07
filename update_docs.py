import re

with open("docs/shinewifi-x2-modbus.md", "r") as f:
    text = f.read()

# I will replace the existing BATTERY and APX MODULES blocks with the expanded versions
new_battery_block = """| **BATTERY APX (HOLDING REGISTERS)** | | | | | | |
| 03 (Hold) | 1001 | Battery Type | U16 | — | 1 | 1: Lithium (APX) |
| 03 (Hold) | 1002 | Design Capacity | U16 | Ah | 1 | Nominal capacity in Amp-hours |
| 03 (Hold) | 1005 | Nominal Energy | U16 | kWh | 0.1 | Total energy (e.g., 50 = 5.0kWh) |
| 03 (Hold) | 3037 | Max Charge Power | U16 | W | 1 | Maximum watts the APX can take |
| 03 (Hold) | 3038 | Max Discharge Power | U16 | W | 1 | Maximum discharge watts |
| **BATTERY APX (BMS & BDC HEALTH)** | | | | | | |
| 04 (Input) | 1013 | Battery SOH | U16 | % | 1 | State of Health (0-100) |
| 04 (Input) | 1017 | Cycle Count | U16 | — | 1 | Lifetime battery cycles |
| 04 (Input) | 3170 | Master SOC | U16 | % | 1 | Aggregated State of Charge |
| 04 (Input) | 3171 | Battery V | U16 | V | 0.1 | Total DC Bus Voltage |
| 04 (Input) | 3172 | Battery I | S16 | A | 0.1 | (+ Charge, - Discharge) |
| 04 (Input) | 3173-74 | Battery P | S32 | W | 0.1 | (+ Charge, - Discharge) |
| 04 (Input) | 3175 | BMS Temperature | U16 | °C | 0.1 | Internal controller temp |
| **APX MODULES (MODULE-LEVEL DEEP DIVE)** | | | | | | |
| 04 (Input) | 5400 / 5500 | Mod 1/2 SOC | U16 | % | 1 | SOC of the 5kWh brick |
| 04 (Input) | 5401 / 5501 | Mod 1/2 Voltage | U16 | V | 0.1 | Actual voltage of that brick |
| 04 (Input) | 5402 / 5502 | Mod 1/2 Current | S16 | A | 0.1 | Amps through that brick |
| 04 (Input) | 5403 / 5503 | Max Cell Temp | U16 | °C | 0.1 | Hottest cell in module |
| 04 (Input) | 5404 / 5504 | Min Cell Temp | U16 | °C | 0.1 | Coldest cell in module |
| 04 (Input) | 5407 / 5507 | Module SOH | U16 | % | 1 | State of Health per brick |
| **ENERGY TOTALS** | | | | | | |"""

pattern = r'\| \*\*BATTERY \(APX\)\*\* \|.*?(?=\| \*\*ENERGY TOTALS\*\* \| \| \| \| \| \| \|)'
replaced = re.sub(pattern, new_battery_block, text, flags=re.DOTALL)

with open("docs/shinewifi-x2-modbus.md", "w") as f:
    f.write(replaced)

