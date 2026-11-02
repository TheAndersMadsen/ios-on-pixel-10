/* SPDX-License-Identifier: MIT */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

struct proc { char p_comm[17]; int pid; };
#define MAXCOMLEN 16
typedef struct { uint64_t pc, lr; bool saved64; } arm_saved_state_t;
typedef struct test_task { uint64_t mach_header_vm_address; } *task_t;
typedef struct test_thread { task_t task; arm_saved_state_t *state; } *thread_t;
typedef struct test_region { uint32_t sr_slide; } *vm_shared_region_t;
struct backtrace_user_info { unsigned int btui_info; int btui_error; };
#define BTUINFO_INIT ((struct backtrace_user_info){0})
#define TUNABLE_STR(var, count, arg, value) char var[count] = value
#define os_atomic_load(p, order) __atomic_load_n((p), __ATOMIC_RELAXED)
#define os_atomic_cmpxchg(p, old, new_value, order) \
	__extension__ ({ unsigned int expected_ = (old); \
	__atomic_compare_exchange_n((p), &expected_, (new_value), false, \
	__ATOMIC_RELAXED, __ATOMIC_RELAXED); })

extern task_t kernel_task;
thread_t current_thread(void);
task_t get_threadtask(thread_t);
arm_saved_state_t *get_user_regs(thread_t);
bool is_saved_state64(const arm_saved_state_t *);
uint64_t get_saved_state_pc(const arm_saved_state_t *);
uint64_t get_saved_state_lr(const arm_saved_state_t *);
int proc_pid(struct proc *);
char *proc_name_address(struct proc *);
vm_shared_region_t vm_shared_region_get(task_t);
void vm_shared_region_deallocate(vm_shared_region_t);
unsigned int backtrace_user(uintptr_t *, unsigned int, const void *, struct backtrace_user_info *);
int hket_test_printf(const char *, ...) __attribute__((format(printf, 1, 2)));
#define printf hket_test_printf
