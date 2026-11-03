#!/bin/sh
# Host test of blazer_usbhost_core.inc against the xHCI/DWC3 model, then the mutants. From this directory. HOST evidence only.
set -eu
cd "$(dirname "$0")"
mkdir -p build
cc -std=c11 -Wall -Wextra -Werror -Wno-unused-function -g -fsanitize=address,undefined -fno-sanitize-recover=all -I../xnu-src test_usbhost.c -o build/test_usbhost
./build/test_usbhost
./mutants.sh
