# Brakovka — Raspberry Pi 4B (Python)

Каталог `rpi_python/` — это перенос логики станка на **Raspberry Pi 4B**:

- Управление:
  - **Кнопки**: GPIO `23, 24, 25, 8, 7` (активный LOW, pull-up)
  - **Частотный преобразователь намотки**: **RS485 Modbus RTU**
    - **USB‑адаптер** (рекомендуется): `/dev/ttyUSB0` или `/dev/serial/by-id/...`, `rs485_de: null`
    - **или** onboard UART: `TX=GPIO14`, `RX=GPIO15`, `DE/RE=GPIO16` (программный DE)
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
```

DE на **GPIO16** (обычный GPIO). Не назначайте на этот пин альтернативную функцию.

```bash
pinctrl get 16
# ожидается: INPUT/OUTPUT
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

**`brakovka_pi/settings.json` не хранится в git** — на каждой машине (ПК, Pi) свой файл.

Первый запуск / клон:

```bash
cp brakovka_pi/settings.json.example brakovka_pi/settings.json
# отредактируйте port, unit_id, machine под своё железо
```

Шаблон в репозитории: `brakovka_pi/settings.json.example`.

По умолчанию приложение читает: `brakovka_pi/settings.json`.

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
- **Поток энкодера:** AS5600 по I2C на максимальной частоте → импульсы и метраж (`wound_m`, `unwind_m`)
- **Цикл контроллера:** скорость `Speed_mpm` = |Δметража| / Δt (по накопленному `wound_length_m`, не по сырым импульсам за тик)
- эмуляция: метраж интегрируется в модели; скорость считается так же в цикле контроллера

PID рассчитывает **частоту для частотника в Hz**.

Важно для единиц:
- `Telemetry/Speed_mpm` — м/мин (из энкодера/модели)
- выход PID — `Telemetry/VfdFreqCmd_Hz` (Hz)
- запись в Modbus — `Hz * 100` в регистр задания частоты

Тюнинг PID настраивается через:
- `Setpoints/PidKp_HzPerMpm`
- `Setpoints/PidTi_s`
- `Setpoints/PidKd_HzSecPerMpm`

Метод PID (`machine.pid_tune_method`):
- `relay` — relay-тест + Ziegler–Nichols (классический PID, по умолчанию)
- `step_imc` — ступенчатый тест + IMC (классический PID с рассчитанными Kp/Ti)
- `pi_ff` — PI + feedforward: `freq = setpoint/mpm_per_hz + PI(error)`; автонастройка калибрует `mpm_per_hz`

Поле `machine.mpm_per_hz` — коэффициент feedforward (м/мин)/Гц для режима `pi_ff`.

### Сглаживание скорости

Скорость считается из приращения метража за период задачи контроллера (`timing.task_period_s`), затем **скользящее среднее по 10 последним значениям** (`PID_REGULATOR_SPEED_AVG_N` в `encoder.py`). Это сглаженное значение идёт в телеметрию/HMI и в регулятор (PID / автонастройка).

Команда на ПЧ (`VfdFreqCmd_Hz`) **не сглаживается** — в Modbus уходит выход PID напрямую.

## Modbus RTU (Delta CP2000)

Используется клиент `pymodbus`. Карта регистров **зафиксирована в коде**
(`VfdConfig` в `brakovka_pi/config.py`), в `settings.json` её нет.

| Регистр | Адрес | Назначение |
|---------|-------|------------|
| `2000H` | 8192 | Команда и статус (чтение) |
| `2001H` | 8193 | Задание частоты: `Hz × 100` (0.01 Гц) |
| `2100H` | 8448 | Авария (опционально): младший байт — fault, старший — warning |
| `2103H` | 8451 | Выходная частота, только чтение |

Команды (регистр `0x2000`): `18` вперёд, `34` назад, `1` стоп.

На ПЧ: `Pr.00-20` = источник частоты RS‑485, `Pr.00-21` = команды RS‑485;
`Pr.09-00` — адрес slave (`serial.unit_id`), `Pr.09-01` — baud.

### USB RS485 (рекомендуется на Pi)

1. Подключите USB‑адаптер, найдите порт:

```bash
bash deploy/list_serial_ports.sh
```

2. В `brakovka_pi/settings.json`:

```json
"serial": {
  "port": "/dev/serial/by-id/usb-ВАШ_АДАПТЕР-if00-port0",
  "baudrate": 115200,
  "unit_id": 1,
  "rs485_de": null,
  "de_delay_before_tx_s": 0,
  "de_turnaround_s": 0
}
```

`rs485_de: null` — **без GPIO DE** (автопереключение в адаптере).

3. Права (один раз):

```bash
sudo usermod -aG dialout rolexs
# перелогиниться
```

4. Проверка:

```bash
pkill -f run_brakovka.py || true
bash deploy/check_modbus_raw.sh
bash deploy/check_modbus.sh
```

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

**RS485 — два варианта**

1. **USB‑адаптер** (`rs485_de: null`): только A/B и GND к ПЧ; DE внутри адаптера.
2. **SP3485 на GPIO** (`rs485_de: 16`): DI←14, RO→15, RSE←16; полярность `rs485_active_high`.

Пин DE в `settings.json`: `serial.rs485_de` — число GPIO или `null` для USB.

## Raspberry Pi: ярлык и обновление с ПК

Шара ПК: `//ROLEXS-DEV/Developments` → `/mnt/pc-git` (см. `/etc/fstab`).

### Ярлык

```bash
cd ~/rpi_python
sed -i 's/\r$//' deploy/*.sh deploy/*.desktop
chmod +x deploy/*.sh
bash deploy/install_desktop_icon.sh
```

### Обновление кода на Pi

`settings.json` в git нет — **`git pull` без stash**:

```bash
cd ~/rpi_python
git pull origin master
```

**Один раз** после перехода на локальный `settings.json` (если pull ругается, что файл будет удалён):

```bash
cp brakovka_pi/settings.json /tmp/settings.json.bak
rm brakovka_pi/settings.json
git pull origin master
cp /tmp/settings.json.bak brakovka_pi/settings.json
```

Первый клон (если нет `settings.json`):

```bash
cp brakovka_pi/settings.json.example brakovka_pi/settings.json
```

Проверка Modbus после обновления:

```bash
pkill -f run_brakovka.py || true
bash deploy/check_modbus.sh
bash deploy/run_brakovka.sh
```

