/*
 * Host test: the touch event shape SweetHIDTouch dispatches (iokit/Kernel/arm/hid/sweet_touch_event.h on branch
 * hk-touch-direct), judged by UIKit's own rule for which touch handler a digitizer collection goes to.
 *
 * The oracle is UIKitCore's code (iOS 26 dyld cache 0f1ee332 in /data/hackios-qemu/dsc-r6), transcribed:
 *   0x18923b208: if event field 0x6 != 0 or type != digitizer -> slot 0; else if IsDisplayIntegrated (0xb0019) == 0
 *                -> slot 0; else slot 1 + (a stylus child exists ? 1 : 0); an empty slot falls back to slot 0.
 *   0x189136238: the first child of type digitizer whose transducer type (0xb0004) is 0 (stylus).
 *   0x18a761c18: UIKit's own synthesized events set IsDisplayIntegrated = !supportsIndirectInputEvents, so slot 0 is
 *                the indirect (trackpad) touch, slot 1 the direct finger, slot 2 the pencil.
 *
 * Build: run.sh. Exits 0 when every check passes.
 */
#include <cstdio>
#include <cstdlib>
#include <map>
#include <vector>
#include "IOHIDEventTypes.h"

struct FakeEvent {
	uint32_t type = kIOHIDEventTypeDigitizer;
	std::map<uint32_t, int64_t> ints;
	std::map<uint32_t, IOFixed> fixed;
	std::vector<FakeEvent> children;
	void setIntegerValue(uint32_t field, int64_t v) { ints[field] = v; }
	void setFixedValue(uint32_t field, IOFixed v) { fixed[field] = v; }
	int64_t get(uint32_t field) const { auto it = ints.find(field); return it == ints.end() ? 0 : it->second; }
	bool has(uint32_t field) const { return ints.count(field) != 0; }
};

#include "sweet_touch_event.h"

static int failures, checks;
#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* UIKit's slot choice, 0x18923b208 + 0x189136238 */
static int
uikit_slot(const FakeEvent &e)
{
	if (e.get(0x6) != 0 || e.type != kIOHIDEventTypeDigitizer) {
		return 0;
	}
	if (e.get(kIOHIDEventFieldDigitizerIsDisplayIntegrated) == 0) {
		return 0;
	}
	for (const FakeEvent &c : e.children) {
		if (c.type == kIOHIDEventTypeDigitizer && c.get(kIOHIDEventFieldDigitizerType) == kIOHIDDigitizerTransducerTypeStylus) {
			return 2;
		}
	}
	return 1;
}

/* SweetHIDTouch::touch() for one finger: digitizerEvent() sets the transducer type, the helpers the rest */
static FakeEvent
one_finger(bool down, bool was, bool moved, bool edge, IOFixed x, IOFixed y, bool direct)
{
	FakeEvent collection, child;
	uint32_t mask = edge ? kIOHIDDigitizerEventFromEdgeTip : 0;

	collection.setIntegerValue(kIOHIDEventFieldDigitizerType, kIOHIDDigitizerTransducerTypeHand);
	child.setIntegerValue(kIOHIDEventFieldDigitizerType, kIOHIDDigitizerTransducerTypeFinger);
	if (was != down) {
		mask |= kIOHIDDigitizerEventTouch | kIOHIDDigitizerEventRange;
	}
	if (moved) {
		mask |= kIOHIDDigitizerEventPosition;
	}
	if (!was && down) {
		mask |= kIOHIDDigitizerEventIdentity;
	}
	sweet_touch_child_fields(&child, 0, 2, down, mask, direct);
	collection.children.push_back(child);
	sweet_touch_collection_fields(&collection, x, y, down, mask, direct);
	return collection;
}

int
main()
{
	const IOFixed x = (IOFixed)((590LL << 16) / 1280), y = (IOFixed)((1648LL << 16) / 2856);  /* the phone's tap at 590,1648 */

	for (int direct = 0; direct <= 1; direct++) {
		FakeEvent down = one_finger(true, false, false, false, x, y, direct), up = one_finger(false, true, false, false, x, y, direct);
		FakeEvent move = one_finger(true, true, true, false, x + 10, y, direct), edge = one_finger(true, false, false, true, 0, y, direct);

		for (const FakeEvent *e : { &down, &up, &move, &edge }) {
			int slot = uikit_slot(*e);
			CHECK(slot == (direct ? 1 : 0), "direct=%d: UIKit slot %d (0 indirect, 1 finger, 2 pencil)", direct, slot);
			CHECK(e->get(kIOHIDEventFieldDigitizerIsDisplayIntegrated) == direct, "collection IsDisplayIntegrated");
			for (const FakeEvent &c : e->children) {
				CHECK(c.get(kIOHIDEventFieldDigitizerIsDisplayIntegrated) == direct, "child IsDisplayIntegrated");
			}
		}
		/* everything else is the pre-fix shape */
		CHECK(down.get(kIOHIDEventFieldDigitizerCollection) == 1, "collection flag");
		CHECK(down.fixed[kIOHIDEventFieldDigitizerX] == x && down.fixed[kIOHIDEventFieldDigitizerY] == y, "collection x/y");
		CHECK(down.get(kIOHIDEventFieldDigitizerRange) == 1 && down.get(kIOHIDEventFieldDigitizerTouch) == 1, "down range/touch");
		CHECK(up.get(kIOHIDEventFieldDigitizerRange) == 0 && up.get(kIOHIDEventFieldDigitizerTouch) == 0, "up range/touch");
		CHECK(down.get(kIOHIDEventFieldDigitizerButtonMask) == 1 && up.get(kIOHIDEventFieldDigitizerButtonMask) == 0, "button mask");
		CHECK(down.get(kIOHIDEventFieldDigitizerEventMask) == (kIOHIDDigitizerEventTouch | kIOHIDDigitizerEventRange | kIOHIDDigitizerEventIdentity),
		    "down mask 0x%llx", (unsigned long long)down.get(kIOHIDEventFieldDigitizerEventMask));
		CHECK(up.get(kIOHIDEventFieldDigitizerEventMask) == (kIOHIDDigitizerEventTouch | kIOHIDDigitizerEventRange), "up mask");
		CHECK(move.get(kIOHIDEventFieldDigitizerEventMask) == kIOHIDDigitizerEventPosition, "move mask");
		CHECK(edge.children[0].get(kIOHIDEventFieldDigitizerEventMask) & kIOHIDDigitizerEventFromEdgeTip, "edge bit kept");
		const FakeEvent &c = down.children[0];
		CHECK(c.get(kIOHIDEventFieldDigitizerIndex) == 0 && c.get(kIOHIDEventFieldDigitizerIdentity) == 2 && c.get(kIOHIDEventFieldDigitizerTouch) == 1,
		    "child index/identity/touch");
		CHECK(c.has(kIOHIDEventFieldDigitizerIsDisplayIntegrated) == (bool)direct, "indirect mode writes no IsDisplayIntegrated field");
	}
	/* the oracle itself: a stylus child would be a pencil, field 0x6 forces slot 0 */
	{
		FakeEvent e = one_finger(true, false, false, false, x, y, true);
		e.children[0].setIntegerValue(kIOHIDEventFieldDigitizerType, kIOHIDDigitizerTransducerTypeStylus);
		CHECK(uikit_slot(e) == 2, "stylus child -> pencil slot");
		e.setIntegerValue(0x6, 1);
		CHECK(uikit_slot(e) == 0, "field 0x6 -> slot 0");
	}
	CHECK(kIOHIDEventFieldDigitizerIsDisplayIntegrated == 0xb0019, "field id 0x%x", kIOHIDEventFieldDigitizerIsDisplayIntegrated);
	printf("touch shape host test: %d checks, %d failed\n", checks, failures);
	return failures != 0;
}
