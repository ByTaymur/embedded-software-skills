# Toolchain / Build / Flash

Work without an IDE (STM32CubeCLT + GCC/CMake) or with Keil/CubeIDE. The project's preferred path is recorded in its `CLAUDE.md`; store the exact commands there. Items here are templates — change paths/part numbers per project.

## STM32CubeCLT + GCC/CMake (IDE-less)

Install STM32CubeCLT (provides `arm-none-eabi-gcc`, `STM32_Programmer_CLI`, CMake support). Add to PATH.

CMake (for CubeMX projects that emit a CMake preset):
```bash
cmake --preset Debug
cmake --build build/Debug
arm-none-eabi-size build/Debug/<project>.elf
```

Plain GCC/Makefile build example:
```bash
arm-none-eabi-gcc -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard \
  -DSTM32F4xx -Iinc -ICMSIS -IHAL/Inc -Wall -Werror -O2 -g3 \
  -T STM32F4xx_FLASH.ld src/*.c -o build/firmware.elf
arm-none-eabi-objcopy -O ihex build/firmware.elf build/firmware.hex
arm-none-eabi-size build/firmware.elf
```
> `-mcpu`, `-mfpu`, `-mfloat-abi`, and the linker script vary by MCU. F1: `-mcpu=cortex-m3`, no FPU. F7/H7: `cortex-m7`, `fpv5`.

## CubeMX headless code generate (no IDE)

```bash
cat > cube.txt << 'EOF'
config load <abs-path>/<project>.ioc
project generate
exit
EOF
<CubeMX-path>/STM32CubeMX -q cube.txt
```
> Use absolute paths; relative paths break headless mode.

## Flash (ST-Link)

STM32CubeProgrammer CLI:
```bash
STM32_Programmer_CLI -c port=SWD -w build/firmware.hex -v -rst
STM32_Programmer_CLI -c port=SWD -e all          # erase all flash
STM32_Programmer_CLI -c port=SWD                  # verify connection/chip
```
OpenOCD (alternative):
```bash
openocd -f interface/stlink.cfg -f target/stm32f4x.cfg \
  -c "program build/firmware.elf verify reset exit"
```

## Common errors & fixes

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `undefined reference` to a HAL function | HAL module disabled in `hal_conf.h` / .c not in build | `#define HAL_xxx_MODULE_ENABLED`; add source to build |
| Linker `region overflow` | Wrong linker script / too much code-RAM | Correct `.ld`; check section sizes |
| Resets / HardFault | Stack/heap overflow, unaligned access, NULL deref | Stack size; read SCB->CFSR in the fault handler |
| Clock wrong / garbled UART baud | Clock config / PLL mismatch with `.ioc` | Align `SystemClock_Config` with `.ioc`; verify HSE value |
| ST-Link "no target" | SWD wiring, NRST, BOOT0, power | Check cable/pins; test with `-c port=SWD` |
| Runs not after flash | Wrong start address / option bytes | Correct flash address (0x08000000); check option bytes |

> Project-specific toolchain paths, part number, linker-script name, and verified build/flash commands go in the "Build & Flash" section of `CLAUDE.md`.
