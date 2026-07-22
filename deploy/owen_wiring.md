# Brakovka — проводка Owen Logic (компактный FB)

**Rev 1.2.0 — 2026-07-22**

`FB_Brakovka`: **~21 вход + ~16 выход** (вместо ~70).  
Редко меняемые уставки (JOG/разгон/autotune step/…) — **внутри ФБ**.

---

## Импорт

1. `brk_globals.csv`
2. ФБ из `.txt` по порядку из заголовка
3. На холсте **один** `FB_Brakovka`, задача **10 мс**

---

## Минимальная схема FBD

### Аварии → один пин
```
xFault := xEncFault OR xVfdFault OR xModbusFault
fbPlant.Fault := xFault
```

### Входы (обязательные)
| Global | Пин |
|--------|-----|
| xEnable | Enable |
| xCmdStart…Autotune | Cmd* |
| xEstopOk | EstopOk |
| udiEncPulseCount | PulseCount |
| xFault | Fault |
| xEmulatorEnable | EmulatorEnable |
| rMetersPerPulse | MetersPerPulse |
| rMaterialThickness_mm | MaterialThickness_mm |
| udiRollLength_m | RollLength_m |
| rCoreDiameter_mm | CoreDiameter_mm |
| rTensionSetpoint_N | TensionSetpoint_N |
| rSpeedSetpoint_mpm | SpeedSetpoint_mpm |
| rTargetLength_m | TargetLength_m |
| rKp / rTi / rMpmPerHz | Kp / Ti / MpmPerHz |

### Выходы
| Пин | Global |
|-----|--------|
| VfdFreq_Hz / VfdRun / VfdReverse | железо ПЧ |
| BrakeValveCmd | тормоз |
| State, AllowRollEdit, SpeedDisp_mpm | HMI |
| WoundLength_m, WoundProgress_pct, UnwindDiameter_mm | HMI |
| AutotuneActive/Done/Failed, AutotuneFailCode | HMI |
| ActiveKp/Ti/MpmPerHz | телеметрия + MOVE |

### После AutotuneDone (1 скан)
```
rKp       := ActiveKp
rTi       := ActiveTi
rMpmPerHz := ActiveMpmPerHz
```

---

## Внутри ФБ (не на холсте)

| Параметр | Значение |
|----------|----------|
| TaskPeriod | 10 мс |
| Jog / Reverse / Slowdown | 10 / 15 / 20 м/мин |
| Accel / Decel / BrakeDelay | 15 / 10 / 3 с |
| Slowdown % | 90 / 85 |
| PiCorrMax | ±20 Гц |
| Autotune step/base/dur/timeout | 12 Гц / 2 с / 10 с / 40 с |
| BrakeGain | 500 Н |
| Фильтры скорости | 100 / 80 / 500 мс |

Чтобы изменить — правьте константы в `VAR` у `FB_Brakovka` и перезалейте ФБ.

---

## HMI

Не больше **32 переменных на один экран** ПР.  
Основные: State, SpeedDisp, Progress, Diameter, команды, Active*/Autotune.
