# Growatt 12KTL3-HU Interaction Specification
**Interface:** Modbus TCP via ShineWifi-X2  
**Protocol Version:** Growatt Modbus RTU Protocol II (Storage/Hybrid)  
**Port:** `502`

## Consolidated Register Map (Function Code 04)

| Address | Name | Type | Unit | Scale | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SYSTEM & PV DATA** | | | | | |
| 3000 | Inverter Status | U16 | — | 1 | 0:Wait, 1:Normal, 3:Fault |
| 3001-02 | PV Total Power | U32 | W | 0.1 | Combined power from all strings |
| 3003-04 | PV1 Voltage / Current | U16×2 | V/A | 0.1 | String 1 |
| 3005-06 | PV1 Power | U32 | W | 0.1 | String 1 Wattage |
| 3007-08 | PV2 Voltage / Current | U16×2 | V/A | 0.1 | String 2 |
| 3009-10 | PV2 Power | U32 | W | 0.1 | String 2 Wattage |
| 3011-12 | PV3 Voltage / Current | U16×2 | V/A | 0.1 | String 3 |
| 3013-14 | PV3 Power | U32 | W | 0.1 | String 3 Wattage |
| 3015-16 | PV4 Voltage / Current | U16×2 | V/A | 0.1 | String 4 |
| 3017-18 | PV4 Power | U32 | W | 0.1 | String 4 Wattage |
| **GRID & METER (3-PHASE)** | | | | | |
| 3030-31 | L1 Voltage / Current | U16×2 | V/A | 0.1 | Inverter Grid Phase 1 |
| 3034-35 | L2 Voltage / Current | U16×2 | V/A | 0.1 | Inverter Grid Phase 2 |
| 3038-39 | L3 Voltage / Current | U16×2 | V/A | 0.1 | Inverter Grid Phase 3 |
| 3042 | Grid Frequency | U16 | Hz | 0.01 | Main frequency (e.g. 5000 = 50.00Hz) |
| 3121-22 | Total Meter Power | S32 | W | 0.1 | Net Power (+ Export, - Import) |
| 3123-24 | Phase L1 Power | S32 | W | 0.1 | Net Power on Phase 1 |
| 3125-26 | Phase L2 Power | S32 | W | 0.1 | Net Power on Phase 2 |
| 3127-28 | Phase L3 Power | S32 | W | 0.1 | Net Power on Phase 3 |
| **HOUSE & EPS (BACKUP)** | | | | | |
| 3048-49 | Total House Load | U32 | W | 0.1 | Calculated property consumption |
| 3118 | EPS Voltage L1 | U16 | V | 0.1 | Voltage on backup port L1 |
| 3120-21 | EPS Total Power | U32 | W | 0.1 | Combined backup load |
| 3130 | EPS Voltage L2 | U16 | V | 0.1 | Voltage on backup port L2 |
| 3131 | EPS Current L1 | U16 | A | 0.1 | Amps on backup Phase 1 |
| 3132 | EPS Voltage L3 | U16 | V | 0.1 | Voltage on backup port L3 |
| 3133 | EPS Current L2 | U16 | A | 0.1 | Amps on backup Phase 2 |
| 3135 | EPS Current L3 | U16 | A | 0.1 | Amps on backup Phase 3 |
| 3136-37 | EPS Power L1 | U32 | W | 0.1 | Backup Load on Phase 1 |
| 3138-39 | EPS Power L2 | U32 | W | 0.1 | Backup Load on Phase 2 |
| 3140-41 | EPS Power L3 | U32 | W | 0.1 | Backup Load on Phase 3 |
| **BATTERY (HIGH VOLTAGE)** | | | | | |
| 3170 | Battery SOC | U16 | % | 1 | State of Charge (0-100) |
| 3171 | Battery Voltage | U16 | V | 0.1 | DC Bus voltage |
| 3172 | Battery Current | S16 | A | 0.1 | Pos: Charge, Neg: Discharge |
| 3173-74 | Battery Power | S32 | W | 0.1 | Pos: Charge, Neg: Discharge |
| 3175 | Battery Temperature | U16 | °C | 0.1 | Internal BMS NTC value |
| **ENERGY COUNTERS (TOTALS)** | | | | | |
| 3053-54 | PV Yield Today | U32 | kWh | 0.1 | Solar generated today |
| 3055-56 | PV Yield Total | U32 | kWh | 0.1 | Solar lifetime |
| 3176-77 | Bat Discharge Today | U32 | kWh | 0.1 | Energy from battery today |
| 3180-81 | Bat Charge Today | U32 | kWh | 0.1 | Energy to battery today |
| 3184-85 | Grid Import Today | U32 | kWh | 0.1 | Bought from grid today |
| 3186-87 | Grid Export Today | U32 | kWh | 0.1 | Sold to grid today |
| 3188-89 | Load Energy Today | U32 | kWh | 0.1 | Total house usage today |
| **DIAGNOSTICS** | | | | | |
| 3091 | Fault Code | U16 | — | 1 | Inverter main error code |
| 3092 | Warning Code | U16 | — | 1 | Inverter warning bitmask |
| 3114 | Inverter Temperature | U16 | °C | 0.1 | Internal heat sink temp |
| 3115 | Boost Temperature | U16 | °C | 0.1 | DC-DC converter temp |