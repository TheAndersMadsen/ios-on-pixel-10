/*
 * Built-in AppleKeyStore for SWEET: a device without a passcode whose
 * system keybag is always loaded and unlocked.
 *
 * Apple's AppleKeyStore kext (closed, SEP-backed) owns the keybags behind
 * data protection. libaks (AppleKeyStore.framework, statically in keybagd)
 * opens IOServiceMatching("AppleKeyStore") with type 0, calls selector 0,
 * then one selector per aks_* function (iOS 16.7 numbering below). keybagd
 * --init asks for the system bag (14) and only loads systembag.kb when the
 * answer is kIOReturnNotFound; answering with a handle is the path a
 * userspace reboot takes, so no bag file is needed.
 *
 * Every call is logged (selector, caller, argument shapes, result) so the
 * next selectors the system needs show up on the console; unknown ones fail
 * with kIOReturnUnsupported. BLAZER_AKS_LOG optionally bounds only repetitive
 * successful Spotlight diagnostics; its runtime gate defaults off.
 */
#include <pexpert/arm64/board_config.h>

#if defined(SWEET)
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOKitKeys.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <libkern/c++/OSString.h>
#include <sys/proc.h>

#ifndef BLAZER_AKS_LOG
#define BLAZER_AKS_LOG 0
#endif
#ifndef BLAZER_AKS_TRACE
#define BLAZER_AKS_TRACE 0
#endif
#if defined(BLAZER) && (BLAZER_AKS_TRACE || BLAZER_AKS_LOG)
#include "blazer_aks_trace.inc"
#endif

/* libaks selectors (AppleKeyStore.framework, iOS 16.7). */
enum {
	kAKSOpen             = 0,
	kAKSCreateBag        = 2,
	kAKSSaveBag          = 3,
	kAKSUnloadBag        = 4,
	kAKSSetSystem        = 5,
	kAKSLoadBag          = 6,
	kAKSGetLockState     = 7,
	kAKSUnlockDevice     = 9,
	kAKSWrapKey          = 10,
	kAKSUnwrapKey        = 11,
	kAKSUnlockBag        = 12,
	kAKSLockBag          = 13,
	kAKSGetSystem        = 14,
	kAKSGetDeviceState   = 17,
	kAKSGetExtDeviceState = 35,     /* aks_get_extended_device_state */
	kAKSAssertHold       = 26,
	kAKSAssertDrop       = 27,
	kAKSUnloadSessionBags = 55,
	kAKSNotifyStateSet   = 102,
	kAKSNotifyStateIsSet = 103,
	kAKSAssertConsume    = 101,     /* aks_assert_consume */
};

/* The system (device) bag handle. */
#define SWEET_AKS_SYSTEM_HANDLE 0

/*
 * aks lock state bits (aks_get_lock_state): bit 2 is "unlocked since boot"
 * (MobileKeyBag MKBDeviceUnlockedSinceBoot); clear lock bits = unlocked.
 */
#define SWEET_AKS_LOCK_STATE    0x4

#ifndef BLAZER_AKS_WRAP
#define BLAZER_AKS_WRAP 0
#endif
#if defined(BLAZER) && BLAZER_AKS_WRAP
/*
 * hackios: aks_wrap_key (10) / aks_unwrap_key (11) in software, so securityd can add keychain items
 * (research/ios26-connectivity-r1/bluetooth/PLAN.md). Compile gate BLAZER_AKS_WRAP and boot-arg
 * blazer_aks_wrap=1, both needed; otherwise both selectors stay kIOReturnUnsupported as before.
 * The secret is read_random() once per boot and never leaves this file: items wrapped in one boot
 * cannot be unwrapped in the next (matches the volatile /private/var keychain).
 */
#include <pexpert/pexpert.h>
extern "C" {      /* corecrypto's headers have no C++ linkage of their own: link to the C symbols */
#include <corecrypto/cchmac.h>
#include <corecrypto/ccsha2.h>
void read_random(void *buffer, unsigned int numBytes);
}
#include "blazer_aks_wrap.inc"

static struct aw_ctx sweet_aks_wrap;

static void
sweet_aks_hmac(const uint8_t *key, size_t key_len, const uint8_t *msg, size_t msg_len, uint8_t out[32])
{
	cchmac(&ccsha256_ltc_di, key_len, key, msg_len, msg, out);
}

static void
sweet_aks_wrap_init(void)
{
	uint32_t on = 0;
	uint8_t secret[AW_SECRET];

	if (!PE_parse_boot_argn("blazer_aks_wrap", &on, sizeof(on)) || on != 1) {
		return;
	}
	read_random(secret, sizeof(secret));
	(void)aw_init(&sweet_aks_wrap, sweet_aks_hmac, secret);
	aw_zero(secret, sizeof(secret));
	IOLog("SWEET AKS: wrap/unwrap on (software, per-boot secret, system bag only)\n");
}

static IOReturn
sweet_aks_wrap_ret(int st)
{
	switch (st) {
	case AW_OK: return kIOReturnSuccess;
	case AW_NO_SPACE: return kIOReturnNoSpace;
	case AW_BAD_HANDLE: return kIOReturnNotFound;
	case AW_NOT_READY: return kIOReturnUnsupported;
	case AW_DECODE: return kIOReturnError;
	case AW_AUTH: return kIOReturnNotPermitted;
	default: return kIOReturnBadArgument;
	}
}

/* Input structure, inband or descriptor, into buf. False if it does not fit. */
static bool
sweet_aks_struct_in(IOExternalMethodArguments *args, uint8_t *buf, uint32_t cap, uint32_t *len)
{
	if (args->structureInputDescriptor != NULL) {
		IOByteCount n = args->structureInputDescriptor->getLength();
		if (n > cap || args->structureInputDescriptor->readBytes(0, buf, n) != n) {
			return false;
		}
		*len = (uint32_t)n;
		return true;
	}
	if (args->structureInput == NULL || args->structureInputSize > cap) {
		return false;
	}
	memcpy(buf, args->structureInput, args->structureInputSize);
	*len = args->structureInputSize;
	return true;
}

/* Output without the trace copy: an unwrapped key must not reach any log. */
static IOReturn
sweet_aks_struct_out_quiet(IOExternalMethodArguments *args, const void *buf, uint32_t len)
{
	if (args->structureOutputDescriptor != NULL) {
		if (len > args->structureOutputDescriptor->getLength() ||
		    args->structureOutputDescriptor->writeBytes(0, buf, len) != len) {
			return kIOReturnNoSpace;
		}
		args->structureOutputDescriptorSize = len;
		return kIOReturnSuccess;
	}
	if (args->structureOutput == NULL || len > args->structureOutputSize) {
		return kIOReturnNoSpace;
	}
	memcpy(args->structureOutput, buf, len);
	args->structureOutputSize = len;
	return kIOReturnSuccess;
}

static IOReturn
sweet_aks_wrap_call(uint32_t selector, IOExternalMethodArguments *args)
{
	uint8_t in[AW_OVERHEAD + AW_KEY_MAX], out[AW_OVERHEAD + AW_KEY_MAX];
	uint32_t in_len = 0, out_len = 0;
	IOReturn ret;
	int st;

	if (!sweet_aks_wrap.ready) {
		return kIOReturnUnsupported;
	}
	if (args->scalarInputCount < 2 || !sweet_aks_struct_in(args, in, sizeof(in), &in_len)) {
		return kIOReturnBadArgument;
	}
	if (selector == kAKSWrapKey) {
		if (args->scalarOutputCount < 1) {
			return kIOReturnBadArgument;
		}
		st = aw_wrap(&sweet_aks_wrap, args->scalarInput[0], args->scalarInput[1], in, in_len, out, sizeof(out), &out_len);
	} else {
		st = aw_unwrap(&sweet_aks_wrap, args->scalarInput[0], args->scalarInput[1], in, in_len, out, sizeof(out), &out_len);
	}
	ret = sweet_aks_wrap_ret(st);
	if (ret == kIOReturnSuccess) {
		ret = sweet_aks_struct_out_quiet(args, out, out_len);
	}
	if (ret == kIOReturnSuccess && selector == kAKSWrapKey) {
		args->scalarOutput[0] = args->scalarInput[1];  /* class_out: the class asked for */
		args->scalarOutputCount = 1;
	} else {
		args->scalarOutputCount = 0;
	}
	if (st != AW_OK) {
		IOLog("SWEET AKS: %s refused: %s\n", selector == kAKSWrapKey ? "wrap" : "unwrap", aw_status_name(st));
	}
	aw_zero(in, sizeof(in));
	aw_zero(out, sizeof(out));
	return ret;
}
#endif /* BLAZER && BLAZER_AKS_WRAP */

class AppleKeyStore : public IOService {
	OSDeclareDefaultStructors(AppleKeyStore);

public:
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(AppleKeyStore, IOService);

bool
AppleKeyStore::start(IOService *provider)
{
	if (!IOService::start(provider)) {
		return false;
	}
#if defined(BLAZER) && BLAZER_AKS_LOG
	blazer_aks_log_init();
#endif
#if defined(BLAZER) && BLAZER_AKS_TRACE
	blazer_aks_trace_init();
#endif
#if defined(BLAZER) && BLAZER_AKS_WRAP
	sweet_aks_wrap_init();
#endif
	setProperty(kIOUserClientClassKey, "AppleKeyStoreUserClient");
	registerService();
	IOLog("SWEET AKS: AppleKeyStore registered (no passcode, unlocked)\n");
	return true;
}

class AppleKeyStoreUserClient : public IOUserClient {
	OSDeclareDefaultStructors(AppleKeyStoreUserClient);

public:
	IOReturn clientClose(void) APPLE_KEXT_OVERRIDE;
	IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *args,
	    IOExternalMethodDispatch *dispatch, OSObject *target,
	    void *reference) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(AppleKeyStoreUserClient, IOUserClient);

IOReturn
AppleKeyStoreUserClient::clientClose(void)
{
	terminate();
	return kIOReturnSuccess;
}

/* Copy len bytes to the caller's output structure (inband or descriptor). */
static IOReturn
sweet_aks_struct_out(IOExternalMethodArguments *args, const void *buf, uint32_t len
#if defined(BLAZER) && (BLAZER_AKS_TRACE || BLAZER_AKS_LOG)
    , struct blazer_aks_trace_copy *trace
#endif
    )
{
#if defined(BLAZER) && (BLAZER_AKS_TRACE || BLAZER_AKS_LOG)
	trace->emitted = len;
#if BLAZER_AKS_TRACE
	if (len >= 2) {
		trace->tag = ((const uint8_t *)buf)[0];
		trace->short_length = ((const uint8_t *)buf)[1];
	}
#endif /* BLAZER_AKS_TRACE */
#endif
	if (args->structureOutputDescriptor != NULL) {
		if (len > args->structureOutputDescriptor->getLength()) {
			return kIOReturnNoSpace;
		}
#if defined(BLAZER) && (BLAZER_AKS_TRACE || BLAZER_AKS_LOG)
		trace->wrote = args->structureOutputDescriptor->writeBytes(0, buf, len);
#else
		args->structureOutputDescriptor->writeBytes(0, buf, len);
#endif
		args->structureOutputDescriptorSize = len;
		return kIOReturnSuccess;
	}
	if (args->structureOutput == NULL || len > args->structureOutputSize) {
		return kIOReturnNoSpace;
	}
	memcpy(args->structureOutput, buf, len);
#if defined(BLAZER) && (BLAZER_AKS_TRACE || BLAZER_AKS_LOG)
	trace->wrote = len;
#endif
	args->structureOutputSize = len;
	return kIOReturnSuccess;
}

/* Append SEQUENCE { UTF8String key, INTEGER value } (short forms only). */
static uint32_t
sweet_aks_der_pair(uint8_t *p, const char *key, uint8_t value)
{
	uint32_t klen = (uint32_t)strlen(key);
	uint32_t n = 0;
	p[n++] = 0x30;
	p[n++] = (uint8_t)(2 + klen + 3);
	p[n++] = 0x0c;
	p[n++] = (uint8_t)klen;
	memcpy(p + n, key, klen);
	n += klen;
	p[n++] = 0x02;
	p[n++] = 0x01;
	p[n++] = value;
	return n;
}

/*
 * Device state (selector 17): a DER SET of key/INTEGER pairs that libaks
 * decode_extended_state reads: ss state, sls lock state (MKBGetDeviceLockState:
 * 0 = unlocked), sb backoff, sfa failed attempts, sgs generation, sas
 * assertions, sgpe grace period, srcd recovery countdown.
 */
static IOReturn
sweet_aks_device_state(IOExternalMethodArguments *args
#if defined(BLAZER) && (BLAZER_AKS_TRACE || BLAZER_AKS_LOG)
    , struct blazer_aks_trace_copy *trace
#endif
    )
{
	static const struct {
		const char *key;
		uint8_t value;
	} fields[] = {
		{ "ss", SWEET_AKS_LOCK_STATE }, { "sls", 0 }, { "sb", 0 }, { "sfa", 0 },
		{ "sgs", 0 }, { "sas", 0 }, { "sgpe", 0 }, { "srcd", 0 },
	};
	uint8_t buf[128];
	uint32_t n = 2;
	for (unsigned int i = 0; i < sizeof(fields) / sizeof(fields[0]); i++) {
		n += sweet_aks_der_pair(buf + n, fields[i].key, fields[i].value);
	}
	buf[0] = 0x31;
	buf[1] = (uint8_t)(n - 2);
	return sweet_aks_struct_out(args, buf, n
#if defined(BLAZER) && (BLAZER_AKS_TRACE || BLAZER_AKS_LOG)
	           , trace
#endif
	           );
}

static uint32_t
sweet_aks_struct_out_size(IOExternalMethodArguments *args)
{
	return args->structureOutputDescriptor != NULL ?
	       (uint32_t)args->structureOutputDescriptor->getLength() : args->structureOutputSize;
}

IOReturn
AppleKeyStoreUserClient::externalMethod(uint32_t selector, IOExternalMethodArguments *args,
    __unused IOExternalMethodDispatch *dispatch, __unused OSObject *target,
    __unused void *reference)
{
	IOReturn ret = kIOReturnSuccess;
#if defined(BLAZER) && (BLAZER_AKS_TRACE || BLAZER_AKS_LOG)
	struct blazer_aks_trace_copy trace = {};
#endif
	uint32_t in_scalars = args->scalarInputCount;
	uint32_t in_struct = args->structureInputDescriptor != NULL ?
	    (uint32_t)args->structureInputDescriptor->getLength() : args->structureInputSize;
	uint32_t out_scalars = args->scalarOutputCount;
	uint32_t out_struct = sweet_aks_struct_out_size(args);
	uint64_t arg0 = in_scalars > 0 ? args->scalarInput[0] : 0;

	switch (selector) {
	case kAKSOpen:
	case kAKSUnloadBag:
	case kAKSSetSystem:
	case kAKSUnlockDevice:
	case kAKSUnlockBag:
	case kAKSLockBag:
	case kAKSAssertHold:
	case kAKSAssertDrop:
	case kAKSAssertConsume:
	case kAKSUnloadSessionBags:
	case kAKSNotifyStateSet:
		args->scalarOutputCount = 0;
		break;
	case kAKSGetSystem:
		if (out_scalars < 1) {
			ret = kIOReturnBadArgument;
			break;
		}
		args->scalarOutput[0] = SWEET_AKS_SYSTEM_HANDLE;
		args->scalarOutputCount = 1;
		break;
	case kAKSGetLockState:
		if (out_scalars < 1) {
			ret = kIOReturnBadArgument;
			break;
		}
		args->scalarOutput[0] = SWEET_AKS_LOCK_STATE;
		args->scalarOutputCount = 1;
		break;
	case kAKSNotifyStateIsSet:
		/* Nothing was ever set: answer "not set". */
		if (out_scalars < 1) {
			ret = kIOReturnBadArgument;
			break;
		}
		args->scalarOutput[0] = 0;
		args->scalarOutputCount = 1;
		break;
	case kAKSGetDeviceState:
	case kAKSGetExtDeviceState:
		args->scalarOutputCount = 0;
		ret = sweet_aks_device_state(args
#if defined(BLAZER) && (BLAZER_AKS_TRACE || BLAZER_AKS_LOG)
	            , &trace
#endif
	            );
		break;
#if defined(BLAZER) && BLAZER_AKS_WRAP
	case kAKSWrapKey:
	case kAKSUnwrapKey:
		ret = sweet_aks_wrap_call(selector, args);
		break;
#endif
	default:
		ret = kIOReturnUnsupported;
		break;
	}

	char name[32];
	proc_selfname(name, sizeof(name));
#if defined(BLAZER) && BLAZER_AKS_LOG
	if (blazer_aks_log_keep(name, selector, args, arg0, in_scalars, in_struct,
	    out_scalars, out_struct, ret, &trace))
#endif
	IOLog("SWEET AKS: %s sel %u arg0 %llu in %u/%u out %u/%u -> 0x%x\n", name, selector,
	    arg0, in_scalars, in_struct, out_scalars, out_struct, ret);
#if defined(BLAZER) && BLAZER_AKS_TRACE
	blazer_aks_trace_report(name, selector, args, in_scalars, in_struct,
	    out_scalars, out_struct, ret, &trace);
#endif
	return ret;
}
#endif /* SWEET */
