# Brakovka — проводка Owen Logic

**Rev 1.5.0 — 2026-07-23**

Задача: **10 мс**.

## На холсте

| Блок | Роль |
|------|------|
| `FB_SpeedCalc` | скорость / WoundLength |
| `FB_UnwindRollDia` | диаметр размотки |
| `FB_BrakeForce` | тормоз |
| `FB_CtrlMach` | автомат, рамп, RUN/REV |
| `FB_CtrlReg` | PI+FF + autotune → частота |
| `FB_BrakovkaEmu` | опц. эмулятор |

`FB_Ctrl` / `FB_MachineCtrl` / `FB_pid_reg` — **больше нет** (заменены).

---

## Импорт

1. `brk_globals.csv`
2. По порядку:
   `FC_LIMIT` → `FC_MaxR` → `FC_MinR` → `FC_Ema` → `FB_PI_Hz` → `FB_SpeedPI_FF` → `FB_AutoTune_PI_FF` → `FB_CtrlReg` → `FB_SpeedCalc` → `FB_UnwindRollDia` → `FB_BrakeForce` → `FB_BrakovkaEmu` → `FB_CtrlMach`

---

## Схема

```
SpeedCalc → ActualSpeed / WoundLength ──┐
                                        ├→ FB_CtrlMach → Ramp / RegEnable / Autotune*
Unwind → Brake ← TensionActive/StopHold ┤         │
                                        │         ↓
                                        └→ FB_CtrlReg → FreqCmd_Hz / Active* / AutotuneDone
                                                  │
                                                  ↓
                                            VfdFreq / VfdRun (см. ниже)
```

### Связи Mach ↔ Reg

| От | К |
|----|---|
| Mach.RampSpeed_mpm | Reg.Setpoint_mpm |
| Mach.RegEnable | Reg.RegEnable |
| Mach.AutotuneMode | Reg.AutotuneMode |
| Mach.AutotuneStart | Reg.AutotuneStart |
| Mach.AutotuneAbort | Reg.AutotuneAbort |
| Mach.AutotuneReset | Reg.AutotuneReset |
| SpeedCalc.SpeedPid | Reg.Actual_mpm и Mach.ActualSpeed |
| Reg.AutotuneBusy | Mach.AutotuneBusy |
| Reg.AutotuneDone | Mach.AutotuneDoneIn |
| Reg.AutotuneFailed | Mach.AutotuneFailedIn |

### Частота / RUN на ПЧ

```
rVfdFreq_Hz := Reg.FreqCmd_Hz

IF Mach.AutotuneActive THEN
    xVfdRun := Reg.RunVFD
ELSE
    xVfdRun := Mach.VfdRun
END_IF
xVfdReverse := Mach.VfdReverse
```

На FBD: SEL / два AND+OR по `AutotuneActive`.

### После AutotuneDone (с Mach или Reg)

```
rKp := ActiveKp
rTi := ActiveTi
rMpmPerHz := ActiveMpmPerHz
```

(`Active*` — выходы **FB_CtrlReg**)

---

## Эмулятор

```
Vfd* (пред. цикл) → Emu → PulseCount → SpeedCalc → Mach/Reg
```

---

## Вложенность

```
FB_CtrlMach          (без вложенных ФБ)
FB_CtrlReg
  ├─ FB_SpeedPI_FF → FB_PI_Hz
  └─ FB_AutoTune_PI_FF
```
