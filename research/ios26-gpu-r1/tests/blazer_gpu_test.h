/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. HOST ONLY: the OS and bus boundary of bsd/dev/blazer_gpu.c.
 * Every CPMQ call, map, delay and register access below is a model in test_survey.c; nothing reaches a device. */
#ifndef BLAZER_GPU_TEST_H
#define BLAZER_GPU_TEST_H
#include <stdint.h>
#include <stdio.h>
typedef uintptr_t vm_offset_t;
typedef uintptr_t vm_size_t;
#define CPMQ_WORDS 4u
#define CPMQ_OK 0
#define CPMQ_SRC_POWER 7u
#define CPMQ_DST_LPB 5u
#define CPMQ_LPB_SET 2u
#define CPMQ_LPB_GPU 20u
int blazer_cpmq_call(uint32_t, uint32_t, const uint32_t *, uint32_t *, uint32_t, uint32_t *);
void blazer_cpmq_lpb_arm(void);
int blazer_cpmq_lpb_wait(uint32_t *, uint32_t *, uint32_t);
const char *cpmq_rc_name(int);
vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
void delay(int);
void blazer_gpu_test_w32(vm_offset_t, uint32_t);
uint32_t blazer_gpu_test_r32(vm_offset_t);
int blazer_gpu_test_printf(const char *, ...) __attribute__((format(printf, 1, 2)));
#define printf blazer_gpu_test_printf
#endif
