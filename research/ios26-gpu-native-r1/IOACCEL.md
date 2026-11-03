# Native accelerator publication: `AGXAccelerator` / `IOAcceleratorES`

Date: 2026-11-04. Agent 6, read-only research. Scope: the IOKit service identity, registry placement, Metal discovery properties, user-client entry point, and its binding to the native submission path. No XNU source, build, Git index, phone, or device state was changed.

Evidence labels: **PHYSICAL** = the named phone log/image; **SOURCE** = source read; **HOST** = existing host-only candidate/receipt; **EXTERNAL** = linked prior art; **INFERENCE** = a conclusion that still needs the stated test.

## 0. Decision

Publish **one** C++ service with this real metaclass ancestry:

```text
IOService
  └── IOAcceleratorES        (existing project class; owns HMGU newUserClient)
        └── AGXAccelerator   (new, empty derived class; inherits HMGU dispatch)
```

Instantiate `AGXAccelerator`, not `IOAcceleratorES`, in `sweet_accel_native_alloc()` (the current UC-r5/native-boot allocation seam). Attach that object under `IOService::getPlatform()`, bind **that same pointer** as the HMGU native provider, set the two Metal plugin properties, recheck the real readiness lease, and only then call `registerService()`.

This one object must produce both userspace results:

```text
IOProviderClass=AGXAccelerator  -> one match
IOProviderClass=IOAcceleratorES -> 1 found, same registry ID
```

Do not create separate AGX and IOAcceleratorES objects, do not rename `AppleCLCD`, do not load Apple's AGX driver, and do not rely on `setName()` or an `IOProviderClass` property for matching. XNU's passive match calls `metaCast()` for `IOProviderClass`, so actual C++ ancestry is sufficient and necessary (`xnu/iokit/Kernel/IOService.cpp:7866-7873`, branch `hk-int3`).

The Metal plugin uses the project's private HMGU ABI. A full `IOGPU` subclass and Apple's `IOGPUDeviceUserClient`/`AGXDeviceUserClient` selector contracts are **not** required for this route. They would be required only if we chose Apple's generic IOGPU/MTLIOAccelDevice path instead of `HMNativeMetal.bundle`.

## 1. What the live `int3` evidence proves

**PHYSICAL:** `research/laguna-usb-fix/attempts/live-20261103-232046-a7-int3/console.txt` shows:

| Log evidence | Meaning for this facet |
|---|---|
| `AppleCLCD` opens at `:1393`, matches at `:1416`, and display is already on | IOKit matching and scanout work. Display publication is not the missing accelerator. |
| backboardd `IOAcceleratorES -> 0 found` at `:1423` | No registered object has `IOAcceleratorES` in its metaclass ancestry. |
| backboardd `AGXAccelerator -> none` at `:1459,1490` | No registered object has the derived `AGXAccelerator` metaclass. |
| SpringBoard `AGXAccelerator -> none` at `:2244`, `IOAcceleratorES -> 0 found` at `:2323` | This is not a backboardd-only query or a display-only issue. |
| SpringBoard `SUICOrbView ... Failed to get Metal device` at `:2329` | The missing registry/plugin path reaches an observable Metal-device failure. |
| `HGLTRACK: SWContext slot wrapped` at `:889` | Composition selected the software context; ordinary DPU activity is not GPU execution. |

The image manifest confirms the immediate cause: `research/images/a7-ios-system-int3/manifest.json:38` has no `hk_accel`, `blazer_hmgu`, or `blazer_native_metal` argument. There is also no accelerator publication line in the log. Therefore this boot is **not evidence of a broken matching algorithm**; the native accelerator driver was never published.

Two existing shortcuts do not solve it:

- `hk_accel=1` in current `hk-int3` would allocate only the base `IOAcceleratorES`, with no Metal properties and no user client (`xnu/iokit/Kernel/arm/sweet_services.cpp:10-27`). It cannot satisfy the AGX query or create a Metal device.
- `HK_ACCEL_ONCE=skip` appears at console `:222,890`. It skips QuartzCore's delay; it neither registers a service nor supplies a device. `research/ios26-phaseb-r1/accel-wait/FINDINGS.md:100-103` separately shows Metal's one-shot enumeration and its `MetalPluginName` gate.

## 2. Prior art: what transfers and what does not

### 2.1 UniXNU native Adreno: closest registry precedent

**EXTERNAL:** UniXNU's Adreno 740 driver defines a custom `AGXAccelerator` derived from `IOAcceleratorES`, with its own `newUserClient`; it does not load Apple's AGX implementation ([`NativeAdrenoAccelerator.cpp`, pin `6fa7bae2`](https://github.com/UniXNU/Adreno740/blob/6fa7bae2a5b3b523e790eb3e0348af4d98969e4d/NativeAdrenoAccelerator.cpp)). Its board publication sets `MetalPluginName`, `MetalPluginClassName`, attaches to `IOService::getPlatform()`, and registers the service ([`GpuPowerProbe.cpp`, pin `965460a9`](https://github.com/UniXNU/UniXNU-sheng/blob/965460a9ac1715636c769634fd0d69f58b2bd0f9/package/GpuPowerProbe.cpp)). Its Metal plugin explicitly documents the discovery chain `IOAcceleratorES -> MetalPluginName -> NSBundle -> principal class -> initWithAcceleratorPort:` and returns a foreign `_MTLDevice` ([`NativeAdrenoMetalPlugin.mm`, pin `243d63cf`](https://github.com/UniXNU/AdrenoMetal/blob/243d63cf43305a85c8119b66b49cb7df4b30b019/NativeAdrenoMetalPlugin.mm)).

Transferable conclusions:

1. A foreign GPU can use a real `AGXAccelerator : IOAcceleratorES` metaclass rather than emulating Apple hardware.
2. Platform-root attachment is sufficient for discovery; the accelerator need not be a child of the display.
3. The plugin can own a private user-client ABI. UniXNU uses open type `0x4147` and refuses the original IOGPU open type rather than pretending to implement it.
4. UniXNU names its client `AGXDeviceUserClient` for stock sandbox compatibility. That is a probe-gated integration consideration, not a Metal discovery requirement.

Do **not** copy these parts blindly:

- UniXNU loads `IOGPUFamily` and stages its derived-class initializer because it inherits Apple's existing base metaclass. This tree already defines its own `IOAcceleratorES`; no such load/staging is needed.
- UniXNU has a separate backend service plus a registry accelerator tied by global state. Our UC-r5 composition can and should keep provider, registry identity, readiness, and UC attachment on one object.
- Its blanket sandbox-grant mechanism is not justified here. First capture the actual HMGU open result and add only the narrow required class/type/selector/memory admissions.
- Its private `IOGPU` layout probe documents a large operational base and vtable surface ([`OriginalGPUProviderABI.h`](https://github.com/UniXNU/AdrenoMetal/blob/243d63cf43305a85c8119b66b49cb7df4b30b019/OriginalGPUProviderABI.h)). We should not fake that surface. Our custom plugin bypasses it.

### 2.2 Apple's actual structure

**EXTERNAL:** Apple's AGX allocation stack shows `AGXAccelerator` calling into `IOGPUFamily` objects and `IOGPUDeviceUserClient`; the userspace wrappers are `IOGPUMetalResource` and AGX-family subclasses ([Project Zero, 2023](https://projectzero.google/2023/10/an-analysis-of-an-in-the-wild-ios-safari-sandbox-escape.html)). Combined with UniXNU's ABI declarations, the useful model is:

```text
Apple: IOAcceleratorES <- IOGPU <- AGXAccelerator <- AGXDeviceUserClient / IOGPUDeviceUserClient
Ours:  IOAcceleratorES <- AGXAccelerator <- HMGPUUserClient <- HMNativeMetal bundle
```

The left side is the class-discovery contract we need. The right side is a private implementation choice. A name-only `IOGPU` or fake Apple user client would add unimplemented private selectors without improving Metal discovery.

### 2.3 Asahi AGX

**EXTERNAL:** Asahi documents AGX firmware, UAT, channels, work queues, completion stamps, and contexts ([AGX documentation](https://asahilinux.org/docs/hw/soc/agx/)); its native implementation is a Linux DRM/Rust driver ([`drivers/gpu/drm/asahi`, branch pin `c8ec9be8`](https://github.com/AsahiLinux/linux/tree/c8ec9be8ec2cae78b0e7affe7044607c2531b005/drivers/gpu/drm/asahi)). It is useful command-path research, but it supplies no IOKit/DriverKit accelerator publication design. macOS already has Apple's AGX accelerator. It also does not make Apple's AGX kext compatible with Tensor's PowerVR DXT firmware contract.

## 3. Exact service and registry design

### 3.1 Metaclass and allocation

Keep the existing base's HMGU override and add an empty derived class in the same C++ translation unit:

```cpp
class AGXAccelerator : public IOAcceleratorES {
    OSDeclareDefaultStructors(AGXAccelerator);
};
OSDefineMetaClassAndStructors(AGXAccelerator, IOAcceleratorES);
```

Change only the native allocation type conceptually:

```text
sweet_accel_native_alloc(parent, out):
    reject invalid arguments / native-disabled state
    a = OSTypeAlloc(AGXAccelerator)
    require a, a->init(), a->attach(parent)
    set registry name
    return a with ownership, still unregistered
```

The inherited `IOAcceleratorES::newUserClient()` remains the only HMGU factory. Required host assertions are `a->metaCast("AGXAccelerator") == a`, `a->metaCast("IOAcceleratorES") == a`, and `a->metaCast("IOService") == a`.

For an especially clear int3 log diff, set the registry name to `AGXAccelerator`; then `matching1` should print `-> AGXAccelerator`. The current candidate's `hmgpu-native` name is also valid and would print `-> hmgpu-native`. **The suffix is the registry name, not the matching test; class match plus registry ID is the test.**

### 3.2 Provider and plane

Use `IOService::getPlatform()` as `parent` for `hmnp_boot_prepare()` in the present built-in composition:

```text
IOService plane
  IOPlatformExpertDevice / platform root
    └── AGXAccelerator ("AGXAccelerator" or "hmgpu-native")
```

Reasons:

- `attach(parent)` puts the object in the IOService registry; `registerService()` publishes it for matching. XNU warns and returns if `registerService()` is called on an object that is not a registry member (`IOService.cpp:1044-1061`).
- Platform-root placement is proven by the foreign-GPU prior art and does not make GPU lifetime depend on display start/stop.
- The existing `sweet_accel_publish(provider)` call from `AppleCLCD::start()` (`SweetFramebuffer.cpp:759`) is legacy bare-service placement. Do not use `disp0` or `AppleCLCD` as the native accelerator's provider merely for convenience.
- There is currently no proven GPU nub/provider with working DT memory and interrupt resources. If a real GPU `IOPlatformDevice` nub is later published, reparenting beneath it is a driver-local change; userspace discovery and HMGU ABI need not change.

`registerService()` returns void, and the current publisher sets its `registered` flag immediately afterward. The implementation proof must additionally check registered state or perform a kernel `copyMatchingService` lookup; an attached-but-unpublished object is a failure, not success.

### 3.3 Exactly one candidate

Preserve the UC-r5 rule that native mode suppresses the legacy `sgx` publication (`uc-r5/tree/.../sweet_services.cpp:53-57`). A bare `IOAcceleratorES` alongside the derived native object would make the count two and lets Metal enumerate a property-less service. For the final registry:

- one `AGXAccelerator` instance;
- one `IOAcceleratorES` match, with the same `IORegistryEntryID`;
- one HMGU `nativeProvider` pointer, equal to that object;
- one readiness supplier bound to that provider;
- zero independent backend/registry pairs.

## 4. Metal discovery properties and bundle contract

Set these as OSStrings on the derived service **after** readiness acquisition and **before** `registerService()`:

| Property | Exact value | Consumer / purpose |
|---|---|---|
| `MetalPluginName` | `../../../private/var/hk/HMNativeMetal` | Metal's `MTLIOAccelServiceGlobalContext` ignores an `IOAcceleratorES` without it. Metal appends `.bundle` beneath `/System/Library/Extensions`; the relative path resolves to `/private/var/hk/HMNativeMetal.bundle`. |
| `MetalPluginClassName` | `HMNativeMetalDevice` | Explicit class selection. It must agree with the bundle's `NSPrincipalClass`. |

`native/metal/runtime/Info.plist:5-10` already names executable `HMNativeMetal` and principal class `HMNativeMetalDevice`. The loader then calls `initWithAcceleratorPort:` and registers a non-nil `_MTLDevice`/`MTLDeviceSPI`; no swizzle or manual `MTLAddDevice` belongs in our code (`metal-r2/notes/INTEGRATION.md:41-45`; `HMNativeMetal.m:136-165`).

Do not publish Apple GPU identity properties (`gpu,t...`) or invent an `IOProviderClass` property. Readiness epoch/generation belongs in trusted kernel state and diagnostic logs, not as user-settable proof properties.

The publication order in `uc-r5/tree/iokit/Kernel/arm/hmnp_xnu.cpp:57-74` is the right base: validate fresh unregistered service and ancestry, acquire lease/facts, set both properties, recheck, register. For CA-facing publication, the lease must additionally authorize the actual render profile; the current UC-r5 supplier advertises **compute only** (`hmnp_ready_xnu.cpp:123-128`).

## 5. User-client type and the submission binding

### 5.1 What Metal chooses versus what the plugin chooses

Metal's discovery layer does **not** dictate our user-client type. It passes the matched `io_service_t` to the bundle. `HMNativeMetalDevice.initWithAcceleratorPort:` then makes the private open:

```text
IOServiceOpen(service, mach_task_self(), 0x484d4755 /* 'HMGU' */, &connection)
```

That is `HMGPU_UC_TYPE` (`hmgpu_uc.h:29`; `native/metal/runtime/src/hmn_iokit.c:23-36`). The derived service inherits the base implementation (`sweet_services.cpp:23-42`), which must:

1. reject null `handler` and clear `*handler`;
2. route only `HMGPU_UC_TYPE` to `HMGPUUserClient`; other types go to the default implementation and must not create a fake Apple client;
3. require `blazer_hmgu=1` and the existing `org.hackios.hmgpu.client` entitlement or administrator privilege;
4. allocate, `initWithTask`, `attach(this)`, and `start(this)` on the **same AGXAccelerator pointer**;
5. leave admission closed when the readiness supplier is absent, stale, closing, or revoked.

The HMGU selector sequence needed by the current runtime is:

- `OPEN=0`: ABI/PVR identity, 16 KiB pages, exact BVNC `0x470002099004bc`, disjoint VA heaps, admitted capabilities and batch limit;
- `BO_CREATE=2`, `BO_IMPORT_SURFACE=4`, and `clientMemoryForType(handle)`: owned BO/IOSurface mappings;
- `CTX_CREATE=5`: native compute context now, render/transfer contexts only when implemented;
- `SUBMIT=9`: returns a sequence number;
- `WAIT=10` and `SET_NOTIFY=11`: real terminal status/completion, never a host-forged success.

Apple's generic IOGPU open type and `IOGPUDeviceUserClient` are deliberately unsupported. A stock sandbox denial must be logged and fixed as a policy/ABI compatibility issue; it must not be mistaken for a matching failure. If live evidence shows the stock profile specifically requires the `AGXDeviceUserClient` class name, use one compatibility-named client class on the same service, not a second backend, and do not copy UniXNU's blanket grant.

### 5.2 Same-object command-path join

The required call chain is:

```text
AGXAccelerator registered with registry ID R
  -> Metal reads plugin properties from R
  -> HMNativeMetalDevice.initWithAcceleratorPort(R)
  -> IOServiceOpen(R, HMGPU_UC_TYPE)
  -> HMGPUUserClient.provider == R and nativeProvider == R
  -> HMGPU_SEL_OPEN
  -> hmnp_uc_apply_open_locked / queueEnsureLocked
  -> nativeFactory.acquire_vm_queue(VM, firmware epoch E)
  -> hq_xnu_create_locked + native context/builders
  -> CTX_CREATE / BO mappings / SUBMIT(ctx, seq)
  -> agents 4/5 firmware CCB/KICK and real engine completion
  -> WAIT/NOTIFY(seq) only after authentic completion + cache handback
  -> agent 8 IOSurface/DPU fence and presentation
```

The binding code already exists in candidate form:

- `hmnp_boot_prepare()` allocates one service, installs it through `hmgu_install_native_queue()`, and creates the supplier (`hmnp_boot_xnu.cpp:17-41`). Pass the platform root and the real native factory here.
- `hmgu_install_native_queue()` stores `nativeProvider = provider` and retains it (`hmgu_queue_xnu.inc:30-39`). This pointer must be the derived AGX object, not its parent or a second service.
- `queueEnsureLocked()` requires `nativeProvider == accelerator`, live firmware admission, a VM, and a same-epoch queue lease (`:49-79`).
- `hmnp_uc_acquire/open/recheck()` binds readiness to the provider, backend, factory, VM, context, and firmware epoch (`hmnp_uc_xnu.inc:129-154`; `hmnp_ready_xnu.cpp:94-140`).
- `HMNativeMetal` refuses device initialization without compiler/streams configuration and a successful HMGU OPEN (`HMNativeMetal.m:144-164`). Registry matching alone therefore cannot produce a device.

**Stop condition:** if publication logs one provider pointer/epoch while OPEN, SUBMIT, or completion names another, the composition is wrong even if both class lookups flip.

## 6. Publication sequence and readiness gates

Use this order in the real integration:

1. Agents 4/5 have a live firmware epoch, usable VM/context/builders, and an actual completion/cache-handback path. KickSync or KCCB consumption alone is insufficient.
2. Allocate the derived service under the platform; do not register it.
3. Install the real HMGU backend and native queue factory on that exact pointer.
4. Create/bind the readiness supplier to that pointer.
5. `acquire`: pin firmware epoch, VM, context, native streams and lifecycle. Validate exact GPU identity, ABI, heaps, capabilities, and batch limit.
6. For an owned compute-only run, require guarded compute output and authentic completion in a run where backboardd/SpringBoard are not consumers.
7. For a normal int3/CA run, additionally require agent 7's render objects/selectors, owned exact-pixel render/readback, agent 8's IOSurface import/pinning and GPU-write-before-DPU-read fencing, and non-headless CA capability. Compute capability must not imply render capability.
8. Set both Metal properties; stage the trusted bundle and compiler provider before consumers can load them.
9. `recheck` the same lease and generation; close admission immediately on staleness.
10. `registerService`; verify one registered match and log class, registry ID, provider identity, epoch, generation, UC type, plugin, and capabilities.
11. On reset/withdrawal, close new HMGU admission before termination and retain service/client/resources until actual DMA quiescence. Removing properties cannot revoke already cached Metal devices.

A normal int3 boot with the current compute-only/headless runtime is **not** a safe intermediate publication: SpringBoard may stop logging “no device” and then fail on texture, render-encoder, or PSO selectors. Use host registry tests and an owned, CA-free validation run before the full consumer boot.

**Boot sequencing:** this facet does not request the next phone boot. The next firmware experiment is the gpu2-derived rung-7 S1–S4 sequence in [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md), with the coremem-only clean-init gate in [COREMEM-INIT.md](COREMEM-INIT.md). That rung deliberately stops before launchd and cannot test IOKit/Metal. The normal-int3 registry probe below belongs to a later stage, after real submission/completion and the intended Metal consumer profile are ready.

## 7. Proving logs and acceptance

### 7.1 Facet acceptance: registry match

Emit one publication line containing at least:

```text
HMNativeMetal: publish class=AGXAccelerator base=IOAcceleratorES registry=<R> provider=<same> epoch=<E> generation=<G> uc=0x484d4755 plugin=../../../private/var/hk/HMNativeMetal caps=<C>
```

The existing queries should change as follows (registry suffix depends on the chosen `setName`):

```text
IOK backboardd:  matching1 <dict ... AGXAccelerator ...> -> AGXAccelerator
IOK SpringBoard: matching1 <dict ... AGXAccelerator ...> -> AGXAccelerator
IOK backboardd:  matching  <dict ... IOAcceleratorES ...> -> 1 found
IOK SpringBoard: matching  <dict ... IOAcceleratorES ...> -> 1 found
```

Both classes must resolve to `R`. `-> hmgpu-native` is equally valid if that remains the registry name. A match without the publication line, properties, or same-ID proof is not this design's acceptance.

For a clean discovery test, remove `HK_ACCEL_ONCE=skip` (or use its non-skipping probe mode) and publish before backboardd starts. QuartzCore's normal first `IOAcceleratorES` poll should then succeed immediately; skipping the poll is unnecessary.

### 7.2 Loader and transport proof

Add/join these lines:

```text
IOK <proc>: open AGXAccelerator type 0x484d4755 -> 0x0
HMNativeMetal: device ready class=HMNativeMetalDevice registry=<R> epoch=<E> capabilities=<C>
HMGU: submit registry=<R> connection=<id> context=<ctx> seq=<S> epoch=<E>
HMGU: done   registry=<R> connection=<id> context=<ctx> seq=<S> engine=<proof> cache=<proof>
```

The open line proves more than matching; its return code distinguishes authorization/sandbox/OPEN failures. The runtime ready line must follow actual OPEN/capability negotiation. Submit/done lines come from agents 4/5 and must use the same R/E/context/sequence.

### 7.3 End-to-end correlation (not supplied by this facet)

Agent 8 should record the actual selected context and join it to submission and presentation:

```text
HGLTRACK: context=<actual GPU-backed class> device=HMNativeMetalDevice submit=<S> done=<S>
```

For the targeted composition, `SUICOrbView ... Failed to get Metal device` must disappear and `SWContext` must not be the selected GPU-compositing fallback. Software contexts can remain for legitimate CPU work. Final acceptance still requires exact rendered pixels, completion/cache handback before DPU reads, and the owner's glass/blur/vibrancy check. Neither a class match nor a non-nil device proves rendering.

## 8. Required tests before the live probe

**HOST / IOKit model:**

1. Register the derived object under a fake platform provider. Match `IOProviderClass=AGXAccelerator` and `IOProviderClass=IOAcceleratorES`; assert identical pointer and registry ID and exactly one base-class result.
2. Prove `setName("IOAcceleratorES")`, `setName("AGXAccelerator")`, and a fake `IOProviderClass` property do not substitute for metaclass ancestry.
3. Verify both property strings byte-for-byte and the bundle's principal class; test missing bundle/class/initializer as explicit loader failures.
4. Call inherited `newUserClient` on the derived object with HMGU type; assert client class, attached provider, and nativeProvider are the same object. Type 0, IOGPU-style type 1, and UniXNU's `0x4147` must not create an HMGU client.
5. Readiness failure, stale epoch, factory mismatch, closing supplier, missing VM/context, and missing render authorization leave the service unregistered or withdraw admission without a false success.
6. Registration-after-attach and registered-state verification are tested; duplicate native allocation/legacy `hk_accel` publication is refused.
7. Timeout/reset/client-death cases retain BOs, mappings, context, service, and lease until actual quiescence.

**Physical probe to request from agent 10, only after the other gates and after the earlier firmware rungs:** one attended normal-int3 boot with the ready derived service, no `HK_ACCEL_ONCE=skip`, the staged signed bundle, and an owned registry/OPEN probe. Capture publication, both class matches and counts, same registry ID, HMGU open result, runtime ready line, and agents 4/5/8's joined submit/done/present lines. Follow [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md) §4.1/§5: the IOK trace has a global 400-line budget, HKL can drop lines, and the current int3 has no backboardd/SpringBoard USTACK. For the later CA/Metal boot, explicitly select `hk_ustack=backboardd,SpringBoard` and clear the default-list `hk_dbg` bit rather than diagnosing a Metal wait from Preferences/MobilePhone stacks. Do not use a name-only service as the phone probe.

## 9. Cross-agent contracts

- **Agents 4/5 (CCB/submission/completion):** supply the real `hmgu_native_queue_factory`, same-epoch VM/context lease, native context/builders, and authentic engine completion/cache evidence. Publish R/E/ctx/seq in submit and done logs. HEALTH, coremem, KCCB consumption, KickSync, and DPU frames do not qualify readiness. Sequence their fail-closed S1–S4 evidence as specified by [COREMEM-INIT.md](COREMEM-INIT.md) and [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md); S4 is still not Metal readiness.
- **Agent 7 (Metal):** keep `HMNativeMetalDevice` and `NSPrincipalClass` identical to `MetalPluginClassName`; stage/sign the bundle and real compiler/streams provider; log OPEN refusal reasons and same-ID device readiness. Do not advertise CA until render PSOs, textures, render/blit encoders, and required selectors are real.
- **Agent 8 (compositor):** supply the measured CA selector/render profile, IOSurface import/pinning and GPU-to-DPU fencing, actual context-class tracking, exact-pixel proof, and joined present completion. Tell agent 6/10 when CA-facing registration is safe.
- **Agent 10 (integration):** pass `IOService::getPlatform()` to native prepare, suppress the legacy bare service, enable only the intended feature gates/boot args, order bundle staging before registration, remove the poll skip for the proof boot, and own sandbox/trust/live-boot coordination. Preserve [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md)'s firmware-first boot order and its explicit backboardd/SpringBoard USTACK instrumentation for the later CA boot.

The two sibling documents above were read and cross-linked after their publication; the remaining cross-agent items are requested contracts, not claims about completed work.

## 10. Risks and stop rules

| Risk | Consequence | Mitigation / stop rule |
|---|---|---|
| Base-only allocation remains in `sweet_accel_native_alloc()` | `IOAcceleratorES` may match, AGX stays `none`. | Instantiate `AGXAccelerator`; host-test both metacasts and same-ID matches. |
| `setName()` used as a class substitute | Log looks plausible but `IOProviderClass` still fails. | Real `OSDefineMetaClassAndStructors` ancestry; no property/name hack. |
| Separate registry and backend providers | Two matches, wrong service selected, OPEN has no native queue/caps. | One derived pointer for registry, nativeProvider, supplier, UC attachment, and readiness. Stop on any ID/pointer mismatch. |
| Register before attach/readiness | Object absent from matching or consumers open an unready backend. | Attach first; acquire/recheck real lease; verify registered state after publication. |
| Compute-only service exposed to normal CA | Metal device appears, then backboardd/SpringBoard crash or render flat/wrong content. | Owned CA-free compute run first. Normal int3 only after render + IOSurface profile passes. |
| Apple `IOGPU`/AGX ABI partially imitated | Private user-client selectors and operational base methods fail unpredictably. | Custom HMNativeMetal plugin and HMGU type; refuse Apple IOGPU opens. Never load Apple AGX for DXT. |
| Sandbox allows match but denies HMGU open/selectors/maps | Registry acceptance passes but device init fails. | Capture open/type/selector/map return codes; add narrow admissions. Do not apply a blanket grant or silently rename without evidence. |
| Duplicate metaclass/kext composition | Apple's IOGPUFamily/AGX or another base definition conflicts with the built-in class. | Keep Apple AGX out; use our already-defined base, with no UniXNU-style parent-metaclass loading. |
| Withdrawal races live clients/DMA | Cached devices access freed VM/BO/context after reset. | Close admission first; retain until actual quiescence; property removal is not revocation. |
| Cosmetic acceptance | AGX match or Metal device is mistaken for native Liquid Glass. | Require same-ID OPEN, actual submit/done/cache, GPU-backed context, ordered presentation, exact pixels, and owner visual confirmation. |

## Bottom line

The minimal correct registry change is small but strict: **allocate a derived `AGXAccelerator`, attach one object under the platform, keep HMGU and readiness on that object, set the two plugin properties, and register only when the intended consumer profile is genuinely ready.** That flips the current class lookups without pretending Tensor's PowerVR is an Apple IOGPU. Everything after the match—plugin OPEN, command execution, completion, and presentation—must remain separately proven and correlated by the same registry ID and firmware epoch.
