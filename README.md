# Brakovka — Raspberry Pi 4B (Python)

Каталог `rpi_python/` — это перенос логики станка на **Raspberry Pi 4B**:

- Управление:
  - **Кнопки**: GPIO `23, 24, 25, 8, 7` (активный LOW, pull-up)
  - **Частотный преобразователь намотки**: **RS485 Modbus RTU** через `/dev/serial0`
    - `TX=GPIO14`, `RX=GPIO15`, `DE/RE=GPIO17` (**UART0 RTS0**)
  - **PWM тормоз размотки**: GPIO `13`
- Взаимодействие с HMI/SCADA: **OPC‑UA server** (DWIN отсутствует)

Основная идея: станок получает команды (импульсные/уровневые) и уставки через OPC‑UA и/или кнопки, читает обратную связь с энкодера (реальный AS5600 или эмуляция), затем:
1) обновляет конечный автомат состояний
2) вычисляет PID-регулятор скорости (в выход “Hz” для частотника)
3) отправляет команды в частотник по Modbus RTU
4) формирует PWM тормоза и публикует телеметрию в OPC‑UA

## Быстрый старт (на Raspberry Pi OS)

1) Включить UART и отключить консоль на нём:
- `sudo raspi-config` → Interface Options → Serial → **Login shell: No**, **Serial port: Yes**
- Проверьте, что `/dev/serial0` указывает на **ttyAMA0** (PL011), а не на **ttyS0** (mini-UART):

```bash
ls -l /dev/serial0
# плохо:  serial0 -> ttyS0
# хорошо: serial0 -> ttyAMA0
```

Если `-> ttyS0`, в `/boot/firmware/config.txt` (или `/boot/config.txt`) добавьте/проверьте:

```
enable_uart=1
dtparam=uart0=on
dtoverlay=disable-bt
gpio=17=a3
```

`gpio=17=a3` включает **RTS0** на GPIO17 для DE/RE преобразователя RS485.
Проверка после reboot:

```bash
pinctrl get 17
# ожидается: ... func=RTS0
```

Затем `sudo reboot`. Mini-UART на 115200 часто даёт «connected, но нет ответа» на Modbus.

2) Установить зависимости:

```bash
sudo apt update
sudo apt install -y python3 python3-pip
python3 -m pip install -r requirements.txt
```

3) GPIO на Debian 13 (Trixie) / Raspberry Pi OS Trixie:

На Trixie **нет `pigpiod`** в apt (ошибка `Can't connect to pigpio at localhost(8888)` —
нормальна, если выбран factory pigpio). Используйте **lgpio**:

```bash
sudo apt update
sudo apt install -y python3-gpiozero python3-lgpio python3-rpi-lgpio
# опционально (клиент pigpio без демона бесполезен для локальных кнопок):
# sudo apt install -y python3-pigpio
```

Принудительно:
```bash
export GPIOZERO_PIN_FACTORY=lgpio
```

В приложении порядок factory по умолчанию: **lgpio → pigpio → rpigpio → native**.

Проверка:

```bash
/home/rolexs/brk/bin/python -c "from gpiozero import Device, Button; from gpiozero.pins.lgpio import LGPIOFactory; Device.pin_factory=LGPIOFactory(); print(Device.pin_factory); b=Button(23, pull_up=True); print('ok', b.value)"
```

Если используете venv — с доступом к system site-packages:

```bash
python3 -m venv --system-site-packages /home/rolexs/brk
/home/rolexs/brk/bin/pip install -r /home/rolexs/rpi_python/requirements.txt
```

4) Запуск:

```bash
# Панель оператора + контроллер (один процесс)
python3 run_brakovka.py

# Только контроллер / SCADA (без Qt)
python3 -m brakovka_pi
# или: BRAKOVKA_HMI=0 python3 run_brakovka.py
```

## Локальная HMI (Qt)

Пакет `brakovka_hmi/` — операторская панель (экраны Главный / Рулон / Настройки / Статус) в **одном процессе** с контроллером.

- Связь UI ↔ `Machine` через `LocalBridge` (без сети и без Modbus).
- **OPC-UA сервер** по-прежнему поднимается для SCADA (`opc.tcp://0.0.0.0:4840/`).
- Команды с панели мержатся с GPIO-кнопками и OPC-UA Commands.
- На Windows/macOS контроллер всегда в эмуляции; HMI работает локально.
- Ввод чисел — **только клавиатура приложения**. Системная OSK Raspberry
  отключается (`QT_IM_MODULE=none`, поля без фокуса ввода). Если OSK всё же
  всплывает из меню Accessibility / «On-screen Keyboard» рабочего стола —
  выключите её в настройках Pi.
- Звуки HMI (клавиши / сохранение / ошибка / авария): `ui.sounds_enabled`
  в `settings.json` (по умолчанию `true`). WAV генерируются в
  `brakovka_hmi/assets/sounds/`.

Зависимость UI: `PySide6` (см. `requirements.txt`).

## Логи

При старте создаётся каталог `logs/` (или путь из `BRAKOVKA_LOG_DIR`):

| Файл | Содержимое |
|------|------------|
| `logs/brakovka_info.log` | INFO / WARNING — работа машины, команды, смена состояний |
| `logs/brakovka_error.log` | ERROR / CRITICAL — аварии энкодера, ПЧ, падения цикла |

Ротация: ~5 МБ × 5 файлов. В консоль/serial не пишется.

## Настройки

По умолчанию: `brakovka_pi/settings.json`.

- Путь: `BRAKOVKA_SETTINGS=/path/settings.json`
- Эмуляция: `BRAKOVKA_EMU=1` или `"emulator": true`
- Пароль экрана «Настройки»: `BRAKOVKA_SETTINGS_PASSWORD` или `ui.settings_password` (по умолчанию `4444`)

После «Сохранить уставки» на HMI секция `machine` **записывается обратно** в JSON.

Основные поля `machine`:
- `unwind_roll_length_m` — метраж разматываемого рулона (диаметр считается)
- `core_diameter_mm`, `material_thickness_mm`
- `target_length_m` — целевая длина намотки потребителя
- скорости / PID / тормоз / разгон

Единая схема уставок: `brakovka_pi/setpoints.py` (HMI / OPC / JSON / `apply_setpoint`).

## Рулон: метраж → диаметр

Оператор задаёт **метраж** загруженного рулона и толщину. Начальный диаметр:

`D² = D_гильзы² + 4 · t · L / π`

Остаток = метраж − размотанное. Текущий диаметр уменьшается по геометрии размотки.

На ходу (`RUN` / `JOG` / …) метраж и толщина **заблокированы**; «Сброс рулона» — с подтверждением.

## Эмуляция (без железа)

В эмуляции (виртуальный режим) не нужно подключать Modbus/AS5600 и можно тестировать:
- логику автомата
- PID (скорость→частота)
- работу OPC‑UA (команды и телеметрия)

Запуск:

```bash
BRAKOVKA_EMU=1 python3 -m brakovka_pi
```

В эмуляции реализовано:
- **виртуальный частотник**: принимает команду (run/reverse/freq) и отдаёт статус
- **виртуальный энкодер**: моделирует скорость по частоте, с инерцией 1‑го порядка
- **рост диаметра потребительского рулона** при намотке, чтобы линейная скорость зависела от текущего диаметра

Коэффициенты модели можно подстраивать:
- `Setpoints/EmuMpmPerHz` — пересчёт частоты (Hz) → базовая скорость (м/мин)
- `Telemetry/EmuConsumerDiameter_mm` — текущий диаметр потребительского рулона в мм

### Механическая модель роста диаметра (для эмуляции)

Используется приближение:

`D^2 = D0^2 + 4 * t * L / pi`

где:
- `D` — текущий диаметр
- `D0` — базовый диаметр сердечника/внутренний диаметр (в модели)
- `t` — толщина материала (берётся из `machine.params.material_thickness_m`)
- `L` — намотанный метраж (в модели)

Также учтён редуктор (в настройках `emu.gear_ratio`).

## Тесты и качество кода

```bash
python -m unittest unit_tests.test_machine -v
# опционально: pip install -e ".[dev]" && ruff check .
```

Конфиг: `pyproject.toml` (ruff / mypy).

## Автозапуск (systemd)

Шаблон юнита: `deploy/brakovka.service`. Скопировать на Pi, поправить пути/`User`, затем:

```bash
sudo cp deploy/brakovka.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now brakovka.service
```

Для полноэкранной HMI удобнее user-unit из графической сессии (autologin).

## Логика конечного автомата (упрощённо)

Состояния: `IDLE`, `RUN`, `JOG`, `REVERSE`, `SLOWDOWN`, `STOPPING`  
(общий enum: `brakovka_pi/state.py`).

Правила переходов:
- `IDLE -> RUN` по `start_pulse` при `estop_ok`, без `stop/jog/reverse`
- `IDLE -> JOG` / `REVERSE` по уровню кнопки
- `RUN -> SLOWDOWN` при достижении `%` целевой длины
- `RUN/SLOWDOWN -> STOPPING` по stop / estop / целевой длине
- `JOG/REVERSE -> STOPPING` при отпускании
- `STOPPING -> IDLE` после `brake_delay_s`

Watchdog: если итерация цикла > 5× `task_period_s` — авария, стоп ПЧ, флаг в телеметрии/HMI.

## Команды: как работают импульсы reset/start

Внутри прошивки Python все команды `Start/Stop/ResetRoll/ResetWound` считаются **импульсами**:
- SCADA/HMI ставит `true`
- после чтения сервер автоматически сбрасывает узел обратно в `false`

Уровневые команды:
- `Jog`, `Reverse` — работают как “держать/отпустить”

### OPC‑UA команды
В группе `Commands`:
- `Start` (bool, импульс)
- `Stop` (bool, импульс)
- `Jog` (bool, уровень)
- `Reverse` (bool, уровень)
- `ResetWound` (bool, импульс)
- `ResetRoll` (bool, импульс)

После импульса:
- `ResetRoll` в коде сбрасывает накопления (и в эмуляции, и в реальном режиме)
- `ResetWound` сбрасывает намотанный метраж

## Скорость и PID

Обратная связь по скорости:
- реальный режим: скорость берётся с **AS5600** по I2C (unwrapping 12‑битного угла)
- эмуляция: скорость моделируется от команды частоты с инерцией

PID рассчитывает **частоту для частотника в Hz**.

Важно для единиц:
- `Telemetry/Speed_mpm` — м/мин (из энкодера/модели)
- выход PID — `Telemetry/VfdFreqCmd_Hz` (Hz)
- запись в Modbus — `Hz * 100` в регистр задания частоты

Тюнинг PID настраивается через:
- `Setpoints/PidKp_HzPerMpm`
- `Setpoints/PidTi_s`
- `Setpoints/PidKd_HzSecPerMpm`

## Modbus RTU (Delta CP2000)

Используется клиент `pymodbus`. Карта по умолчанию — **Delta CP2000** (`settings.json` → `"vfd"`).

| Регистр | Адрес | Назначение |
|---------|-------|------------|
| `2000H` | 8192 | Команда (`reg_cmd`) и статус (`reg_status`, чтение) |
| `2001H` | 8193 | Задание частоты (`reg_freq`): `Hz × 100` (0.01 Гц) |
| `2100H` | 8448 | Авария (`reg_fault`, опционально): младший байт — fault, старший — warning |
| `2103H` | 8451 | Выходная частота (`reg_freq_out`), только чтение |

На ПЧ: `Pr.00-20` = источник частоты RS‑485, `Pr.00-21` = команды RS‑485; `Pr.09-00` — адрес slave, `Pr.09-01` — baud.

`VfdStatusWord/VfdErrorCode` публикуются в OPC‑UA.

## OPC‑UA API (структура узлов)

Сервер поднимается на: `opc.tcp://0.0.0.0:4840/`

Экспортирует объект `Brakovka`:

### `Brakovka/Telemetry/*`
- `State` (string)
- `Speed_mpm` (float)
- `Wound_m` (float, намотанный метраж)
- `Brake_pct` (float)
- `UnwindDiameter_mm` (float, текущий диаметр размотки)
- `StartDiameter_mm` (float, расчётный начальный диаметр, только чтение)
- `EncoderError` (bool)
- `MagnetOk` (bool, AS5600 MD)
- `WatchdogFault` (bool)
- `VfdStatusWord` / `VfdErrorCode` / `VfdFault` / `VfdWarning`
- `VfdFreqCmd_Hz` (float)
- `EmuConsumerDiameter_mm` (float, только в эмуляции)

### `Brakovka/Commands/*`
- `Start` (bool, импульс)
- `Stop` (bool, импульс)
- `Jog` (bool, уровень)
- `Reverse` (bool, уровень)
- `ResetWound` (bool, импульс)
- `ResetRoll` (bool, импульс) — перед сбросом применяет roll-уставки из OPC Setpoints
- `ApplySetpoints` (bool, импульс) — явно применить все Setpoints с SCADA в Machine

Уставки с локальной HMI применяются только по кнопкам «Сохранить уставки» /
«Сброс рулона» и затем синхронизируются в OPC Setpoints. SCADA меняет Machine
только по `ApplySetpoints` (все Setpoints) или `ResetRoll` (roll-уставки + сброс).
Запись в Setpoints без этих команд лишь готовит значения в узлах.

### `Brakovka/Setpoints/*`
- `SpeedSetpoint_mpm`, `TargetLength_m`, `UnwindRollLength_m`, `MaterialThickness_mm`
- `RollEncoder_mm`, PID (`PidKp` / `PidTi` / `PidKd`)
- `TensionSetpoint_N`, `TensionBrakeGain_N`, `TensionBrakeMin_pct`
- `SlowdownSpeed_mpm`, `SlowdownStart_pct`, `AccelTime_s`, `DecelTime_s`
- `EmuMpmPerHz` (эмуляция)

## Примечания по GPIO

Кнопки ожидаются как **активный LOW** (подтяжка вверх).

**RS485 DE/RE** по умолчанию — **UART0 RTS0 на GPIO17** (`serial.de_mode=uart_rts` в `settings.json`).
Ядро/pyserial автоматически поднимает RTS на время TX и опускает для RX
(`serial.rs485.RS485Settings`). Проводка: DI←GPIO14, RO→GPIO15, RSE←GPIO17.

Запасной режим: `"de_mode": "gpio"` — программный выход на `rs485_de` (без RTS0).

В `config.txt` обязательно: `gpio=17=a3` (иначе GPIO17 не RTS0).

