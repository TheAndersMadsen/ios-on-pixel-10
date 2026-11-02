/* SPDX-License-Identifier: MIT */
#define BLAZER 1
#define HKET_HOST_TEST 1
#include "../blazer_exit_trace.c"
#undef printf
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>

static struct test_task user_task = {0x101000000}, kern;
task_t kernel_task = &kern;
static arm_saved_state_t state = {0x180000100, 0x101001004, true};
static struct test_thread thread = {&user_task, &state};
static struct test_region region = {0x800000};
static bool have_region = true;
static unsigned int unwind_count = HKET_FRAME_LIMIT;
static int unwind_error;
static unsigned int calls, released, headers, ends, printed_frames, invalid_counts;
static char last_header[512], last_end[256];
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static struct proc selected = {"bluetoothd", 66};

thread_t current_thread(void) { return &thread; }
task_t get_threadtask(thread_t t) { return t->task; }
arm_saved_state_t *get_user_regs(thread_t t) { return t->state; }
bool is_saved_state64(const arm_saved_state_t *s) { return s->saved64; }
uint64_t get_saved_state_pc(const arm_saved_state_t *s) { return s->pc; }
uint64_t get_saved_state_lr(const arm_saved_state_t *s) { return s->lr; }
int proc_pid(struct proc *p) { return p->pid; }
char *proc_name_address(struct proc *p) { return p->p_comm; }
vm_shared_region_t vm_shared_region_get(task_t t) { assert(t == &user_task); return have_region ? &region : NULL; }
void vm_shared_region_deallocate(vm_shared_region_t r) { assert(r == &region); __atomic_add_fetch(&released, 1, __ATOMIC_RELAXED); }

unsigned int
backtrace_user(uintptr_t *bt, unsigned int cap, const void *ctl, struct backtrace_user_info *info)
{
	assert(cap == HKET_FRAME_LIMIT && ctl == NULL);
	__atomic_add_fetch(&calls, 1, __ATOMIC_RELAXED);
	for (unsigned int i = 0; i < cap && i < unwind_count; i++) bt[i] = 0x101000100u + i * 4u;
	info->btui_error = unwind_error;
	info->btui_info = unwind_error ? 1u : 0u;
	return unwind_count;
}

int
hket_test_printf(const char *fmt, ...)
{
	char text[512];
	va_list args;
	va_start(args, fmt);
	int n = vsnprintf(text, sizeof(text), fmt, args);
	va_end(args);
	assert(n > 0 && (size_t)n < sizeof(text));
	pthread_mutex_lock(&lock);
	if (strstr(text, " exit(")) { headers++; strcpy(last_header, text); }
	else if (strstr(text, " end frames ")) { ends++; strcpy(last_end, text); }
	else if (strstr(text, " frame ")) printed_frames++;
	else if (strstr(text, " invalid_count ")) invalid_counts++;
	else assert(!"unexpected trace record");
	pthread_mutex_unlock(&lock);
	return n;
}

static void reset(void)
{
	hket_records = calls = released = headers = ends = printed_frames = invalid_counts = 0;
	hket_name[0] = '\0';
	last_header[0] = last_end[0] = '\0';
	thread.task = &user_task; thread.state = &state; state.saved64 = true;
	have_region = true; unwind_count = HKET_FRAME_LIMIT; unwind_error = 0;
}

static void *one_exit(void *arg)
{
	unsigned int *continued = arg;
	blazer_exit_trace(&selected, 1);
	__atomic_add_fetch(continued, 1, __ATOMIC_RELAXED);
	return NULL;
}

int main(void)
{
	reset();
	blazer_exit_trace(&selected, 1);
	assert(headers == 0 && calls == 0);
	strcpy(hket_name, "bluetoothd");
	struct proc wrong = {"bluetooth", 70};
	blazer_exit_trace(&wrong, 1);
	blazer_exit_trace(NULL, 1);
	strcpy(hket_name, "bluetoothd-extra-long");
	blazer_exit_trace(&selected, 1);
	assert(headers == 0 && hket_records == 0);
	strcpy(hket_name, "bluetoothd");
	thread.state = NULL; blazer_exit_trace(&selected, 1);
	thread.state = &state; state.saved64 = false; blazer_exit_trace(&selected, 1);
	state.saved64 = true; thread.task = kernel_task; blazer_exit_trace(&selected, 1);
	thread.task = NULL; blazer_exit_trace(&selected, 1);
	assert(headers == 0 && hket_records == 0);
	thread.task = &user_task;
	unsigned int continued = 0;
	one_exit(&continued);
	assert(continued == 1 && headers == 1 && ends == 1 && printed_frames == 12);
	assert(calls == 1 && released == 1);
	assert(strstr(last_header, "main 0x101000000 shared_slide 0x800000 shared_known 1"));
	assert(strstr(last_end, "end frames 12 error 0 info 0x0"));

	unwind_count = 0; unwind_error = EFAULT; have_region = false;
	one_exit(&continued);
	assert(continued == 2 && ends == 2 && printed_frames == 12 && released == 1);
	assert(strstr(last_header, "shared_slide 0x0 shared_known 0"));
	assert(strstr(last_end, "end frames 0 error 14 info 0x1"));
	unwind_count = HKET_FRAME_LIMIT + 1; unwind_error = 0;
	one_exit(&continued);
	assert(continued == 3 && ends == 3 && printed_frames == 24 && invalid_counts == 1);

	reset(); strcpy(hket_name, "bluetoothd"); continued = 0;
	pthread_t workers[64];
	for (unsigned int i = 0; i < 64; i++) assert(pthread_create(&workers[i], NULL, one_exit, &continued) == 0);
	for (unsigned int i = 0; i < 64; i++) assert(pthread_join(workers[i], NULL) == 0);
	assert(continued == 64 && hket_records == 32 && headers == 32 && ends == 32);
	assert(calls == 32 && printed_frames == 384 && released == 32);
	one_exit(&continued);
	assert(continued == 65 && headers == 32 && calls == 32);
	puts("PASS actual exit tracer: off/filter/state/return/fault/bounds/concurrent cap");
	return 0;
}
