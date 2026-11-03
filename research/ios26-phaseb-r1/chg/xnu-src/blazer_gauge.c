/*
 * The Pixel 10 Pro's (blazer, Tensor G5) battery as iOS sees it: the max77779 fuel gauge, READ ONLY, through the AP's own
 * SPMI master. Own code. Facts only from GPL vendor source (spmi-smartdv.c, regmap-goog-spmi.c, bms/max77779_*) and from
 * FDT laguna.dtb d7c27fdc. Evidence and the full access list: research/ios26-battery-r1/FINDINGS.md.
 *
 *   blazer_battery=1      read, log and feed SweetBattery's IOPMPowerSource, once a minute
 *   blazer_battery=2      boot probe: hold bsd_init, look at the controller, read, log, panic. Needs blazer_panic=1.
 *                         SweetBattery stays static and nothing else touches the controller
 *   blazer_battery_chg=1  also read the charger's status (SID 3). Off: the owner's approval names the gauge, so without
 *                         this the charger's slave address never goes on the bus, external power stays reported as present
 *                         and charging is inferred from the current
 *   blazer_battery_chg=2  report only: read the charger's status, its programmed limits (charge current, float voltage, input
 *                         limits, mode, watchdog) and its input ADCs, and print them as one line per sample (blazer_charger.h
 *                         decodes them). What iOS is told stays exactly what it is without the charger: the line is the
 *                         only output. Still no write opcode; CHG_INT/CHG_INT2 (read-to-clear latches) are never read
 *
 * What this file can put on the bus: only the rows of FRAMES below, whose command words are compile-time constants.
 * Opcode 3 is EXT_REG_READ. Nothing else builds a REQ_COMMAND word, there is no write opcode in this file, and no
 * register outside the SPMI master's own is touched: no pad, clock, reset, PMIC or CPM mailbox.
 *
 * FDT spmi@53f1000: "smartdv,spmi", reg 0x53f1000 size 0x300, no clocks, power-domains, resets or interrupts, so nothing to
 * vote and completion is polled, as the vendor driver does then. That is IRQ_STATUS of this block, not a mailbox.
 *
 * Physical, 20261102-034251-batt-probe-r4: ABL leaves CONTROL at 0x00010191: master on, arbitration off, prescaler 4. That's the state its
 * own reads of this gauge ran in; its last REQ_COMMAND, 0x004a020e, is this file's word form (slave 4, 0x94, 1 byte). So this file never
 * writes CONTROL, unlike the vendor's driver, which programs the FDT's 0x4192. That value, tried once, gave DONE plus bit 10, the arbitration timer.
 */
#if defined(BLAZER) || defined(BLAZER_GAUGE_HOST)

#ifdef BLAZER_GAUGE_HOST
#include "host_shim.h"
#else
#include <IOKit/IOLib.h>
#include <kern/clock.h>
#include <kern/debug.h>
#include <libkern/libkern.h>
#include <machine/machine_routines.h>
#include <mach/mach_types.h>
#include <os/atomic_private.h>
#include <pexpert/pexpert.h>

extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
#endif
#include "blazer_gauge.h"
#include "blazer_gauge_ext.h"
#include "blazer_charger.h"

#define SPMI_PA                 0x053f1000ULL   /* FDT */
#define SPMI_SIZE               0x300           /* FDT. A 16 KiB mapping also covers its neighbours, which nothing here reads */

/* spmi-smartdv.c. Not listed, never touched: RSP_ADDR_DATA 0xc, TIMER 0x2c, TBT_RST_CONTROL 0x30, the FIFOs 0x38-0x300. */
#define SPMI_CONTROL            0x00u
#define SPMI_IRQ_ENABLE         0x04u           /* looked at, never written */
#define SPMI_IRQ_STATUS         0x08u
#define SPMI_REQ_COMMAND        0x10u
#define SPMI_REQ_DATA0          0x14u
#define SPMI_REQ_DATA1          0x18u
#define SPMI_REQ_DATA2          0x1cu
#define SPMI_REQ_DATA3          0x20u
#define SPMI_REQ_RD_STATUS      0x24u
#define SPMI_RD_ERR_INDEX       0x28u
#define SPMI_STATUS             0x34u           /* looked at once, never written */

/* What the ABL of that run, deepspace-17.4-16424240, leaves: master on, arbitration off, id 0, spmi_ver 1, arb_retry_limit 6, prescaler 4. Read, never written. */
#define SPMI_CONTROL_ABL        ((1u << 0) | (0u << 1) | (0u << 2) | (1u << 4) | (6u << 6) | (4u << 14))
_Static_assert(SPMI_CONTROL_ABL == 0x00010191u, "ABL's CONTROL");

#define SPMI_IRQ_DONE           (1u << 0)
/* The vendor's SPMI_ANY_ERROR_IRQ_FLAG, bits 2-9, exactly. Bit 10, the arbitration timer, isn't one: the check is on the data, DevName and ranges. */
#define SPMI_IRQ_ERRORS         (0xffu << 2)
#define SPMI_POLL_US            5u
#define SPMI_POLLS              (100000u / SPMI_POLL_US)        /* the driver's REQ_COMMAND_TIMEOUT_MS */

/* REQ_COMMAND: new command, primary arbitration, opcode, slave, byte count - 1, register. Opcode is not a parameter. */
#define SPMI_OP_EXT_REG_READ    3u
#define SPMI_READ_WORD(sid, reg, bytes) \
	(1u | (1u << 1) | (SPMI_OP_EXT_REG_READ << 2) | ((uint32_t)(sid) << 7) | (((uint32_t)(bytes) - 1u) << 11) | ((uint32_t)(reg) << 15))

#define SID_GAUGE               6u      /* FDT max77779fg@6, reg <6 0> */
#define SID_CHARGER             3u      /* FDT max77779chrg@3, reg <3 0> */

/*
 * Every frame this file can send. Gauge registers are 8-bit addressed and 16-bit wide (max77779_fg_spmi.c), charger
 * registers 8-bit wide (max77779_charger_spmi.c). The vendor's kernel drivers read all but DevName in normal running, ABL's log shows
 * DevName, and their regmaps declare no precious (read-sensitive) register. CHG_INT 0xb0, CHG_INT2 0xb1, the charger's latches, aren't here.
 */
#define FRAMES(X) \
	X(DEVNAME,    SID_GAUGE,   0x21, 2) \
	X(REPSOC,     SID_GAUGE,   0x07, 2) \
	X(VCELL,      SID_GAUGE,   0x1a, 2) \
	X(CURRENT,    SID_GAUGE,   0x1c, 2) \
	X(AVGCURRENT, SID_GAUGE,   0x1d, 2) \
	X(TEMP,       SID_GAUGE,   0x1b, 2) \
	X(FSTAT,      SID_GAUGE,   0x3d, 2) \
	X(CHG_INT_OK, SID_CHARGER, 0xb6, 1) \
	X(CHG_DTLS0,  SID_CHARGER, 0xb7, 1) \
	X(CHG_DTLS1,  SID_CHARGER, 0xb8, 1) \
	X(CHG_DTLS2,  SID_CHARGER, 0xb9, 1) \
	X(CHG_DTLS3,  SID_CHARGER, 0xba, 1) \
	X(CHG_CNFG00, SID_CHARGER, 0xbc, 1) \
	X(CHG_CNFG02, SID_CHARGER, 0xbe, 1) \
	X(CHG_CNFG04, SID_CHARGER, 0xc0, 1) \
	X(CHG_CNFG09, SID_CHARGER, 0xc5, 1) \
	X(CHG_CNFG10, SID_CHARGER, 0xc6, 1) \
	X(CHG_CNFG15, SID_CHARGER, 0xcb, 1) \
	X(CHGIN_I,    SID_CHARGER, 0x00, 2) \
	X(CHGIN_V,    SID_CHARGER, 0x02, 2) \
	X(WCIN_I,     SID_CHARGER, 0x04, 2) \
	X(WCIN_V,     SID_CHARGER, 0x06, 2)

#define X(name, sid, reg, bytes) F_##name,
enum { FRAMES(X) F_COUNT };
#undef X

#define X(name, sid, reg, bytes) \
	_Static_assert(((SPMI_READ_WORD(sid, reg, bytes) >> 2) & 0x1fu) == 3u, "EXT_REG_READ only"); \
	_Static_assert((sid) == SID_GAUGE || ((sid) == SID_CHARGER && \
	    (((reg) >= 0xb6 && (reg) <= 0xba && (bytes) == 1) || (reg) == 0xbc || (reg) == 0xbe || (reg) == 0xc0 || \
	    (reg) == 0xc5 || (reg) == 0xc6 || (reg) == 0xcb || \
	    (((reg) == 0x00 || (reg) == 0x02 || (reg) == 0x04 || (reg) == 0x06) && (bytes) == 2))), \
	    "gauge, or the charger's status, named CNFG bytes and input ADC words only: never CHG_INT 0xb0/0xb1");
FRAMES(X)
#undef X

/* The object's check reads this table back: tools/check_objects.py. */
#define X(name, sid, reg, bytes) SPMI_READ_WORD(sid, reg, bytes),
__attribute__((used)) const uint32_t blazer_gauge_frames[F_COUNT] = { FRAMES(X) };
#undef X

#define X(name, sid, reg, bytes) #name,
static const char *const frame_name[F_COUNT] = { FRAMES(X) };
#undef X

/* Units. maxfg_common.h: VCell 78.125 uV, Temp 1/256 C, RepSOC 1/256 %. max77779_fg.c: 1.5625 uV / RSENSE, 2 mOhm: no rsense in this FDT, driver's default. */
#define VCELL_UV_NUM            78125u
#define VCELL_UV_DEN            1000u
#define CURRENT_UA_NUM          156250
#define RSENSE_10UOHM           200
#define DEVNAME_RADIX           0x51u   /* ABL's log on this phone: FG device name 0x5100 */
#define FSTAT_DNR               (1u << 0)       /* data not ready: bms/max77779_v20240115_regs.h */
#define CHARGING_MA_FLOOR       20      /* without the charger's word: average current into the battery above this counts */
#define GIVE_UP_AFTER           3       /* samples failed in a row */

#define SAMPLES_IN_PROBE        3
#define PROBE_LOOKS             200
#define PROBE_LOOK_MS           10
#define PROBE_HOLD_MS           5000
#define PROBE_SAMPLE_GAP_MS     10000

static vm_offset_t gauge_regs;
static uint32_t gauge_frames_sent, gauge_samples, gauge_bad_in_a_row, gauge_command_left;
static bool gauge_dead;
static uint32_t ext_arg;         /* blazer_battery_ext=1: external and the warnings follow the current */
static struct gauge_ext gauge_ext = { .external = true };
static uint64_t gauge_last;     /* blazer_gauge_peek. One word, so a reader can't see half a sample */
static uint32_t mode_arg, charger_arg;
static bool args_read;

static uint32_t
spmi_rd(uint32_t off)
{
#ifdef BLAZER_GAUGE_HOST
	return host_spmi_rd(off);       /* the host test's fake controller (write-1-to-clear, transfers on REQ_COMMAND) */
#else
	uint32_t value = *(volatile uint32_t *)(gauge_regs + off);

	__asm__ volatile ("dmb oshld" ::: "memory");
	return value;
#endif
}

static void
spmi_wr(uint32_t off, uint32_t value)
{
#ifdef BLAZER_GAUGE_HOST
	host_spmi_wr(off, value);
#else
	__asm__ volatile ("dmb oshst" ::: "memory");
	*(volatile uint32_t *)(gauge_regs + off) = value;
#endif
}

static void
read_args(void)
{
	uint32_t mode = 0, charger = 0;

	/* SweetBattery's start and bsd_init can both ask first: a second parse is harmless, seeing a half-done one wouldn't be. */
	if (os_atomic_load(&args_read, acquire)) {
		return;
	}
	(void)PE_parse_boot_argn("blazer_battery", &mode, sizeof(mode));
	(void)PE_parse_boot_argn("blazer_battery_chg", &charger, sizeof(charger));
	(void)PE_parse_boot_argn("blazer_battery_ext", &ext_arg, sizeof(ext_arg));
	if (mode > 2) {
		printf("blazer-battery: blazer_battery=%u means nothing: off\n", mode);
		mode = 0;
	}
	if (charger > 2) {
		printf("blazer-battery: blazer_battery_chg=%u means nothing: no charger frames\n", charger);
		charger = 0;
	}
	mode_arg = mode;
	charger_arg = charger;
	os_atomic_store(&args_read, true, release);
}

uint32_t
blazer_gauge_mode(void)
{
	read_args();
	return mode_arg;
}

bool
blazer_gauge_gave_up(void)
{
	return gauge_dead;
}

static void
give_up(const char *why)
{
	if (!gauge_dead) {
		gauge_dead = true;
		printf("blazer-battery: leaving the controller alone from here on: %s\n", why);
	}
}

/*
 * One bus transfer, the vendor's sequence, smartdv_spmi_read_cmd and smartdv_spmi_xfer, in the state ABL leaves and with no write to CONTROL.
 * Stricter than the vendor's: it stops if CONTROL isn't ABL's value or REQ_COMMAND moved, and clears a stale DONE before it can pass for ours.
 */
__attribute__((noinline)) static bool
spmi_frame(unsigned frame, uint32_t *value)
{
	uint32_t control, status, command, data;
	unsigned polls;

	if (frame >= F_COUNT || gauge_dead || gauge_regs == 0) {
		return false;
	}
	/* Nothing here writes this register, so at every frame it must still be what ABL left. Anything else: a different loader, or another writer. */
	control = spmi_rd(SPMI_CONTROL);
	if (control != SPMI_CONTROL_ABL) {
		printf("blazer-battery: CONTROL is %08x, ABL leaves %08x\n", control, SPMI_CONTROL_ABL);
		give_up(control == 0xffffffffu ? "CONTROL reads all ones" : "someone else drives this controller");
		return false;
	}
	/*
	 * The vendor's driver takes no lock against firmware here, and a read of ours would trample a write in progress if firmware
	 * shared these registers. A 10 ms look can't see a 10 us transfer, but this register holds what was last sent: whatever it
	 * holds after our frame, it must still hold before the next. Only reads, and if it changes nothing more goes out this boot.
	 */
	if (gauge_frames_sent != 0) {
		command = spmi_rd(SPMI_REQ_COMMAND);
		if (command != gauge_command_left) {
			printf("blazer-battery: REQ_COMMAND is %08x, it held %08x after our frame\n", command, gauge_command_left);
			give_up("someone else sends on this controller");
			return false;
		}
	}
	status = spmi_rd(SPMI_IRQ_STATUS);
	if (gauge_frames_sent == 0) {
		uint32_t enabled = spmi_rd(SPMI_IRQ_ENABLE);

		printf("blazer-battery: before our first frame CONTROL=%08x IRQ_ENABLE=%08x IRQ_STATUS=%08x\n", control, enabled, status);
		/*
		 * The FDT gives this block no interrupt and this kernel handles none of it, but it doesn't reset SPIs at the GIC, as Linux
		 * does. If ABL left this enabled, a frame's DONE could fire one nobody clears. Stop and say so: clearing it is another write.
		 */
		if (enabled != 0) {
			give_up("IRQ_ENABLE is set");
			return false;
		}
	}
	if (status != 0) {
		spmi_wr(SPMI_IRQ_STATUS, status);
		if (spmi_rd(SPMI_IRQ_STATUS) & SPMI_IRQ_DONE) {
			give_up("a stale DONE doesn't clear");
			return false;
		}
	}
	spmi_wr(SPMI_REQ_DATA0, 0);
	spmi_wr(SPMI_REQ_DATA1, 0);
	spmi_wr(SPMI_REQ_DATA2, 0);
	spmi_wr(SPMI_REQ_DATA3, 0);
	spmi_wr(SPMI_REQ_RD_STATUS, 0);
	spmi_wr(SPMI_REQ_COMMAND, blazer_gauge_frames[frame]);
	status = 0;
	/* As the vendor polls: for DONE alone. An error comes with DONE. */
	for (polls = 0; polls < SPMI_POLLS; polls++) {
		status = spmi_rd(SPMI_IRQ_STATUS);
		if (status & SPMI_IRQ_DONE) {
			break;
		}
		delay(SPMI_POLL_US);
	}
	spmi_wr(SPMI_IRQ_STATUS, status);
	gauge_command_left = spmi_rd(SPMI_REQ_COMMAND);
	if (gauge_frames_sent++ == 0) {
		printf("blazer-battery: we sent %08x, REQ_COMMAND now reads %08x\n", blazer_gauge_frames[frame], gauge_command_left);
	}
	if (!(status & SPMI_IRQ_DONE)) {
		printf("blazer-battery: %s: no DONE in 100 ms, IRQ_STATUS=%08x\n", frame_name[frame], status);
		give_up("a transfer timed out");
		return false;
	}
	/* Read and logged before the verdict: a refused frame must still say what it carried. */
	data = spmi_rd(SPMI_REQ_DATA0);
	if (mode_arg == 2 || gauge_frames_sent == 1) {
		printf("blazer-battery: %s: IRQ_STATUS=%08x REQ_DATA0=%08x\n", frame_name[frame], status, data);
	}
	if (status & SPMI_IRQ_ERRORS) {
		printf("blazer-battery: %s: error bits, REQ_RD_STATUS=%08x RD_ERR_INDEX=%08x\n", frame_name[frame], spmi_rd(SPMI_REQ_RD_STATUS), spmi_rd(SPMI_RD_ERR_INDEX));
		return false;
	}
	*value = data;
	return true;
}

static bool
read16(unsigned frame, uint16_t *out)
{
	uint32_t value;

	if (!spmi_frame(frame, &value)) {
		return false;
	}
	*out = (uint16_t)value;
	return true;
}

static bool
read8(unsigned frame, uint8_t *out)
{
	uint32_t value;

	if (!spmi_frame(frame, &value)) {
		return false;
	}
	*out = (uint8_t)value;
	return true;
}

/* Who is plugged in and what is the charger doing: max77779_is_online and max77779_get_status. Reads only. */
static bool
read_charger(struct blazer_gauge_sample *s)
{
	uint8_t ok, d0, d1, d2;
	unsigned chgin, wcin, chg;

	if (!read8(F_CHG_INT_OK, &ok) || !read8(F_CHG_DTLS0, &d0) || !read8(F_CHG_DTLS1, &d1) || !read8(F_CHG_DTLS2, &d2)) {
		return false;
	}
	chgin = (d0 >> 5) & 3u;
	wcin = (d0 >> 3) & 3u;
	chg = d1 & 0xfu;
	s->charger_read = true;
	s->external = chgin >= 2 || wcin >= 2;
	s->charging = s->external && chg <= 3;  /* dead-battery, constant current, constant voltage, top-off */
	s->full = s->external && chg == 4;      /* done */
	printf("blazer-battery: charger INT_OK=%02x DTLS0=%02x DTLS1=%02x DTLS2=%02x chgin=%u wcin=%u chg=%u\n", ok, d0, d1, d2, chgin, wcin, chg);
	return true;
}

/*
 * blazer_battery_chg=2: everything the charger says about itself, one line, nothing kept. Reads only, all of them in the vendor
 * regmap's readable range (max77779_chg_is_reg) and outside its interrupt latches. A failed frame ends this sample's line, not the
 * gauge's sample: what iOS sees never depends on these.
 */
static uint32_t charger_reports;

static void
report_charger(void)
{
	struct blazer_charger_regs r;
	struct blazer_charger_view v;
	const char *chg;
	char chg_buf[12];

	memset(&r, 0, sizeof(r));
	if (!read8(F_CHG_INT_OK, &r.int_ok) || !read8(F_CHG_DTLS0, &r.d0) || !read8(F_CHG_DTLS1, &r.d1) || !read8(F_CHG_DTLS2, &r.d2) ||
	    !read8(F_CHG_DTLS3, &r.d3) || !read8(F_CHG_CNFG00, &r.cnfg00) || !read8(F_CHG_CNFG02, &r.cnfg02) ||
	    !read8(F_CHG_CNFG04, &r.cnfg04) || !read8(F_CHG_CNFG09, &r.cnfg09) || !read8(F_CHG_CNFG10, &r.cnfg10) ||
	    !read8(F_CHG_CNFG15, &r.cnfg15) || !read16(F_CHGIN_I, &r.chgin_i) || !read16(F_CHGIN_V, &r.chgin_v) ||
	    !read16(F_WCIN_I, &r.wcin_i) || !read16(F_WCIN_V, &r.wcin_v)) {
		printf("blazer-battery: charger report %u unread\n", charger_reports + 1);
		return;
	}
	charger_reports++;
	blazer_charger_decode(&r, &v);
	chg = blazer_charger_chg_name(v.chg_dtls);
	if (chg == 0) {
		snprintf(chg_buf, sizeof(chg_buf), "dtls%x", v.chg_dtls);
		chg = chg_buf;
	}
	printf("blazer-battery: charger %u in=%s chg=%s mode=%x cp=%u wdt=%u cc=%u mA cv=%u mV icl=%u mA wicl=%u mA ichgin=%u mA iwcin=%u mA vwcin=%u mV"
	    " vchgin_raw=%04x ok=%02x dtls=%02x%02x%02x%02x bat=%u\n",
	    charger_reports, blazer_charger_in_name(&v), chg, v.mode, v.cp_en, v.wdt_en, v.cc_ma, v.cv_mv, v.icl_ma, v.wicl_ma,
	    v.ichgin_ma, v.iwcin_ma, v.vwcin_mv, r.chgin_v, r.int_ok, r.d0, r.d1, r.d2, r.d3, v.bat_dtls);
	if (!v.cv_valid) {
		printf("blazer-battery: charger %u CHG_CV_PRM %02x has no voltage in the vendor's table\n", charger_reports, r.cnfg04);
	}
}

bool
blazer_gauge_read(struct blazer_gauge_sample *out)
{
	struct blazer_gauge_sample s;
	uint16_t name, soc, vcell, current, average, temp, fstat;
	bool good;

	if (gauge_dead || gauge_regs == 0) {
		return false;
	}
	memset(&s, 0, sizeof(s));
	gauge_samples++;
	/* The identity first: if it's wrong nothing else goes out. */
	good = read16(F_DEVNAME, &name);
	if (good && (name >> 8) != DEVNAME_RADIX) {
		printf("blazer-battery: DevName=%04x, not the gauge\n", name);
		give_up("slave 6 isn't the gauge");
		return false;
	}
	good = good && read16(F_REPSOC, &soc) && read16(F_VCELL, &vcell) && read16(F_CURRENT, &current) &&
	    read16(F_AVGCURRENT, &average) && read16(F_TEMP, &temp) && read16(F_FSTAT, &fstat);
	if (good) {
		s.percent = soc >> 8;
		s.mv = (uint32_t)(((uint64_t)vcell * VCELL_UV_NUM / VCELL_UV_DEN) / 1000u);
		s.ma = (int32_t)((int64_t)(int16_t)current * CURRENT_UA_NUM / RSENSE_10UOHM / 1000);
		s.ma_avg = (int32_t)((int64_t)(int16_t)average * CURRENT_UA_NUM / RSENSE_10UOHM / 1000);
		s.centi_c = (int32_t)(int16_t)temp * 100 / 256;
		printf("blazer-battery: sample %u SOC(%u), VCELL(%u), INOW(%d), IAVG(%d), TEMP(%d), raw soc %04x vcell %04x i %04x iavg %04x t %04x fstat %04x dev %04x\n",
		    gauge_samples, s.percent, s.mv, s.ma, s.ma_avg, s.centi_c, soc, vcell, current, average, temp, fstat, name);
		/* Nothing implausible reaches iOS: a wrong 0% would ask it to shut down. */
		good = !(fstat & FSTAT_DNR) && s.percent <= 100 && s.mv >= 2800 && s.mv <= 4800 && s.ma > -12000 && s.ma < 12000 &&
		    s.ma_avg > -12000 && s.ma_avg < 12000 && s.centi_c > -3000 && s.centi_c < 9000;
		if (!good) {
			printf("blazer-battery: sample %u refused: not ready or out of range\n", gauge_samples);
		}
	}
	if (good) {
		/*
		 * Without the charger's word, external stays what every UI boot has reported. r3's powerd takes Power Source State, Show Charging UI
		 * and Play Charging Chime from it, and r3's keep-awake keys include SBDontDimOrLockOnAC. Near float the current sits around this floor,
		 * so reading external from it would flip iOS between AC and battery with nothing plugged or unplugged.
		 */
		s.charging = s.ma_avg > CHARGING_MA_FLOOR;
		s.external = true;
		if (charger_arg == 2) {
			report_charger();
		}
		if (charger_arg == 1 && !read_charger(&s)) {
			/* The gauge's numbers stand, and so does the state from above. */
			printf("blazer-battery: charger state unread: inferred from the current\n");
		}
		if (ext_arg == 1 && charger_arg != 1) {
			bool was = gauge_ext.external;

			s.external = gauge_ext_step(&gauge_ext, s.ma, s.ma_avg);
			s.charging = s.external && s.charging;
			if (was != s.external) {
				printf("blazer-battery: external %d, from the current, at %d mA, %u%%\n", s.external, s.ma_avg, s.percent);
			}
		}
		if (ext_arg == 1) {
			s.warn = gauge_warn(s.external, s.percent);
			s.critical = gauge_critical(s.external, s.percent);
		}
		gauge_bad_in_a_row = 0;
		__atomic_store_n(&gauge_last, (uint64_t)(gauge_samples & 0xffu) << 56 | (uint64_t)s.percent << 48 | (uint64_t)s.mv << 32 |
		    (uint64_t)(uint16_t)(int16_t)s.ma_avg << 16 | (uint16_t)(int16_t)(s.centi_c / 10), __ATOMIC_RELEASE);
		*out = s;
		return true;
	}
	if (++gauge_bad_in_a_row >= GIVE_UP_AFTER) {
		give_up("three bad samples in a row");
	}
	return false;
}

uint64_t
blazer_gauge_peek(void)
{
	return __atomic_load_n(&gauge_last, __ATOMIC_ACQUIRE);
}

bool
blazer_gauge_start(void)
{
	read_args();
	if (gauge_regs == 0) {
		printf("blazer-battery: mapping %#llx size %#x, mode %u, charger reads %s\n", SPMI_PA, SPMI_SIZE, mode_arg, charger_arg == 1 ? "on" : charger_arg == 2 ? "report only" : "off");
		gauge_regs = ml_io_map((vm_offset_t)SPMI_PA, SPMI_SIZE);
	}
	return gauge_regs != 0;
}

/* No write and no bus traffic: what ABL left, and whether anything else is moving these registers. */
static bool
probe_look(void)
{
	uint32_t control, status, command, c, s;
	unsigned control_moves = 0, status_moves = 0;

	printf("blazer-battery: about to read the controller for the first time\n");
	control = spmi_rd(SPMI_CONTROL);
	status = spmi_rd(SPMI_IRQ_STATUS);
	command = spmi_rd(SPMI_REQ_COMMAND);
	printf("blazer-battery: look CONTROL=%08x IRQ_ENABLE=%08x IRQ_STATUS=%08x REQ_COMMAND=%08x REQ_RD_STATUS=%08x STATUS=%08x\n",
	    control, spmi_rd(SPMI_IRQ_ENABLE), status, command, spmi_rd(SPMI_REQ_RD_STATUS), spmi_rd(SPMI_STATUS));
	if (control == 0xffffffffu || status == 0xffffffffu) {
		give_up("reads all ones: not a live block");
		return false;
	}
	for (unsigned i = 0; i < PROBE_LOOKS; i++) {
		IOSleep(PROBE_LOOK_MS);
		c = spmi_rd(SPMI_CONTROL);
		s = spmi_rd(SPMI_IRQ_STATUS);
		control_moves += c != control;
		status_moves += s != status;
		control = c;
		status = s;
	}
	printf("blazer-battery: look %u times over %u ms: CONTROL moved %u, IRQ_STATUS moved %u\n", PROBE_LOOKS, PROBE_LOOKS * PROBE_LOOK_MS, control_moves, status_moves);
	if (control_moves != 0) {
		give_up("someone else drives this controller");
		return false;
	}
	printf("blazer-battery: holding %u ms with no bus traffic\n", PROBE_HOLD_MS);
	IOSleep(PROBE_HOLD_MS);
	c = spmi_rd(SPMI_REQ_COMMAND);
	printf("blazer-battery: REQ_COMMAND was %08x, after the hold %08x\n", command, c);
	if (c != command) {
		give_up("someone else sends on this controller");
		return false;
	}
	return true;
}

void
blazer_gauge_boot_probe(void)
{
	struct blazer_gauge_sample s;
	uint32_t panic_arg = 0;
	uint16_t name = 0;
	unsigned good = 0;

	if (blazer_gauge_mode() != 2) {
		return;
	}
	if (!PE_parse_boot_argn("blazer_panic", &panic_arg, sizeof(panic_arg)) || panic_arg == 0) {
		printf("blazer-battery: probe refused: it ends in a panic, so it needs blazer_panic=1\n");
		return;
	}
	if (!blazer_gauge_start()) {
		panic("blazer-battery: probe: no mapping");
	}
	if (probe_look()) {
		/* One frame, then a pause: an error that lands late still points at the right step. */
		printf("blazer-battery: about to send the first frame: DevName, slave 6\n");
		if (read16(F_DEVNAME, &name)) {
			printf("blazer-battery: first frame: DevName=%04x, ABL's 5100\n", name);
			if ((name >> 8) != DEVNAME_RADIX) {
				give_up("slave 6 isn't the gauge");
			}
		} else {
			give_up("the first frame failed");
		}
		IOSleep(PROBE_HOLD_MS);
		for (unsigned i = 0; i < SAMPLES_IN_PROBE && !gauge_dead; i++) {
			good += blazer_gauge_read(&s);
			IOSleep(PROBE_SAMPLE_GAP_MS);
		}
		if (!gauge_dead) {
			printf("blazer-battery: look after CONTROL=%08x IRQ_STATUS=%08x\n", spmi_rd(SPMI_CONTROL), spmi_rd(SPMI_IRQ_STATUS));
		}
	}
	panic("blazer-battery: probe done: %u good samples, %u frames, %s", good, gauge_frames_sent, gauge_dead ? "gave up" : good == SAMPLES_IN_PROBE ? "all well" : "bad samples");
}

#endif /* BLAZER */
