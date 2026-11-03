# Metal device creation, the native accelerator contract, and IOSurface textures

Date: 2026-11-04. Owner facet: agent 7, userspace Metal/IOKit/IOSurface design. **Read-only research:** no XNU edit, build, build lock, Git operation, or phone action was performed. The only intentional file written is this document.

Evidence labels: **PHYSICAL** = the named int3 phone capture; **CACHE** = offline disassembly/symbol reading of the phone's iOS 26 dyld cache; **SOURCE** = repository source; **PRIOR ART** = linked external work; **DESIGN** = a proposed implementation, not a result. Cache: `/data/hackios-qemu/dsc-r6/dyld_shared_cache_arm64e`, UUID `0f1ee33235db30f38f5fbd4b954138d5`, read with `dsc_sym.py` and the bounded disassembly helpers.

## 0. Decision

Use the **custom `HMNativeMetal.bundle` path**, not Apple's `MTLIOAccelDevice`/`IOGPUMetalDevice` protocol. Agent 6 should publish **one** real C++ `AGXAccelerator` object derived from the project's `IOAcceleratorES`, with two string properties and the HMGU user client on that same object. Metal's own loader will then load our bundle, construct `HMNativeMetalDevice`, and call `MTLAddDevice`; no framework patch, swizzle, manual `MTLAddDevice`, or Apple AGX driver is needed.

The accelerator properties alone are not sufficient. A non-nil device also needs a loadable signed bundle, a **real configured compiler/streams provider**, successful HMGU authorization/`OPEN`, and exactly one usable Metal device. CA-facing publication must additionally wait for concrete render/transfer/IOSurface support. Publishing today's compute-only/headless class to SpringBoard could remove the SUICOrbView message and then fail on its next queue/texture/PSO/encoder call; that is not the requested hardware-compositor result.

The implementation order is therefore:

1. clean firmware and real compute/VM/completion (agents 1-5), then an **owned** device/compute probe;
2. an owned transfer blit and the existing clear/triangle/quad known-pixel tests;
3. IOSurface-backed rendering and presentation fencing (agents 3/8);
4. only then CA-facing `AGXAccelerator` registration and the SpringBoard/backboardd acceptance.

This preserves the firmware gates in [COREMEM-INIT.md](COREMEM-INIT.md) and [FIRMWARE.md](FIRMWARE.md), the submission contract in [CCB-KICK.md](CCB-KICK.md), the registry design in [IOACCEL.md](IOACCEL.md), the VM/fence requirements in [MMU.md](MMU.md), and the ordered integration in [PLAN.md](PLAN.md) / [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md): KickSync is not compute, a non-nil device is not rendering, and DPU activity is not GPU completion.

## 1. What the live log proves, and what it does not

PHYSICAL, `research/laguna-usb-fix/attempts/live-20261103-232046-a7-int3/console.txt`:

| Line | Observation | Consequence |
|---|---|---|
| 889 | `HGLTRACK: SWContext slot wrapped` | The instrumentation wrapped a software-context slot. It is not a GPU context or execution receipt. |
| 890 | `HK_ACCEL_ONCE=skip` skipped QuartzCore's accelerator wait | It creates no service. A native image must not let this skip race ahead of native publication. |
| 1423, 2323 | backboardd/SpringBoard `IOAcceleratorES -> 0 found` | Metal has no service to enumerate. |
| 1459, 1490, 2244 | both processes `AGXAccelerator -> none` | The separate QuartzCore class query also fails. A single derived native service must satisfy both lookups. |
| 2329 | `SUICOrbView ... Failed to get Metal device for GPU rendering` | This follows the missing enumerable/plugin-bearing service; it is not evidence of a shader failure. |
| 1470-1473, 2325-2328 | `IOCoreSurfaceRoot` opens successfully | IOSurface allocation/IPC is already independent of the missing accelerator. |
| 1494 | BGRA 1125x2511, bpr 4608, size 11583488 | This is the exact initial GPU-import shape to support, not a compressed/AGX layout. |

There are no backboardd/SpringBoard stacks in this capture; `LIVE-EVIDENCE.md` §5 gives the later USTACK instrumentation. HGLTRACK currently supplies a slide, not a call stack or selected-device identity. The final receipt must therefore add an explicit context/device/submit/done record rather than merely deleting `SWContext` text. Software contexts may legitimately remain for CPU work; the requirement is that **composition selects a real GPU-backed context**.

## 2. Exact iOS 26 Metal discovery path — CACHE

The following is the actual cache path, not an inference from prior art.

### 2.1 Enumeration and bundle loading

`-[MTLIOAccelServiceGlobalContext init]` at Metal `0x186115d08`:

1. calls `IOMainPort`, `IOServiceMatching("IOAcceleratorES")`, and `IOServiceGetMatchingServices` once;
2. for each service calls helper `0x186115e54`;
3. allocates a request with `initWithAcceleratorPort:deviceClass:` and later processes it.

The helper at `0x186115e54` does exactly this:

1. `IORegistryEntryCreateCFProperty(service, @"MetalPluginName", ...)`; missing or non-CFString rejects the service;
2. constructs `"/System/Library/Extensions" + MetalPluginName + ".bundle"` and calls `+[NSBundle bundleWithPath:]`;
3. reads `MetalPluginClassName` as a CFString and calls `-[NSBundle classNamed:]`; absent/unusable class name falls back to `-[NSBundle principalClass]`;
4. requires `isSubclassOfClass:_MTLDevice`, otherwise returns nil.

`processPendingCreateIOAccelServiceRequests` at `0x186116190` then performs `[[deviceClass alloc] initWithAcceleratorPort:port]`. A non-nil result goes to `_MTLAddDevice` (`0x186126b04`). `_MTLAddDevice` requires conformance to **both** `MTLDevice` and `MTLDeviceSPI`, then sends `initLimits`, `initFeatureQueries`, and `initWorkarounds`.

`MTLCreateSystemDefaultDevice` (`0x1860dbfd8`) returns the sole registered device. Its block at `0x1860dc158` takes index zero when count is one and takes the “doesn't know what to do with more than one device” path when count exceeds one. **Do not leave a second bare/native accelerator with Metal properties.**

### 2.2 Required registry values for agent 6

| Item | Exact requirement |
|---|---|
| C++ identity | One actual `AGXAccelerator` subclass of the project's `IOAcceleratorES`; `setName()` alone cannot satisfy `IOProviderClass`. Both class matches must resolve to this same object. |
| `MetalPluginName` | String `../../../private/var/hk/HMNativeMetal` (no `.bundle`; Metal appends it). |
| `MetalPluginClassName` | String `HMNativeMetalDevice`. |
| Bundle | `/private/var/hk/HMNativeMetal.bundle`, `NSPrincipalClass=HMNativeMetalDevice`, subclass of `_MTLDevice`, loadable in the calling process. |
| Registration | Install the real HMGU `newUserClient`, acquire/recheck the native readiness lease, set both properties, then `registerService()`. No name-only or health-only publication. |
| Count | Suppress the bare `hk_accel=1`/second Metal-bearing service. There must be one default device, not two unrelated backends. |
| Timing | Publish before QuartzCore's first enumeration. For bring-up, remove `HK_ACCEL_ONCE=skip`; do not publish a property-less placeholder merely to end the wait. |

SOURCE agrees: `research/ios26-metal-native-20261102/metal-r2/src/hmnp_xnu.cpp:48-63` already sets the two properties and readiness checks. Its `metaCast("IOAcceleratorES")` continues to pass on the derived object. `native/metal/runtime/Info.plist` names the same principal class.

### 2.3 What `HMNativeMetalDevice.initWithAcceleratorPort:` still requires

SOURCE `native/metal/runtime/src/HMNativeMetal.m:144-164` currently does this in order:

1. install/load a compiler and require configured peers plus `MTLDeviceSPI` conformance;
2. retain the accelerator port and obtain its real 64-bit registry ID;
3. `IOServiceOpen(port, mach_task_self(), HMGPU_UC_TYPE, &connection)`;
4. selector `HMGPU_SEL_OPEN` and validation of the returned PVR facts;
5. construct the core device and return self.

Thus these are independent fail points that need distinct logs:

- **Compiler:** `hmn_loader.m:41-55` loads the adjacent `HMNativeMetal.bundle/HMNativeMetalCompiler.dylib` only when the adjacent `HMNativeMetal.enable` contains exactly 16 bytes `HMNativeMetal 1\n`. Trusted static composition can instead call `HMNativeMetalInstallCompiler`. Today's source has no production provider; an absent/test provider is a hard stop, not something agent 6 can repair with properties.
- **Code loading:** agent 10 must stage the bundle and nested dylibs with the chosen iOS 26 pointer-auth/signing policy, sandbox-readable path, and library-validation compatibility. An SDK link or ad hoc host signature does not prove SpringBoard can load it.
- **Authorization:** HMGU type is `0x484d4755` (`'HMGU'`). `HMGPUUserClient.cpp:83-91` requires current non-kernel task plus either boolean entitlement `org.hackios.hmgpu.client` or administrator privilege. The entitlement belongs to the **calling process**, not the bundle. Agent 10 must provide it to the owned probe and, at CA stage, backboardd/SpringBoard, or use a separately reviewed authorization design. Metal itself showed no entitlement check in the loader above. Sandbox admission is a separate check: capture open/type/selector/map return codes and add only narrow required admissions, using `IOACCEL.md` §5's compatibility-named client only if live evidence requires it.
- **OPEN facts:** ABI 1, backend `HMGPU_BACKEND_PVR`, core ID `0x470002099004bc`, page size 16384, nonzero `max_jobs_per_submit`, valid disjoint general/USC/PDS VA heaps, and only known capability bits. `hmn_device_create` additionally requires `HMGPU_CAP_COMPUTE` and real compiler callbacks. CA profile must also have genuine `RENDER` and `TRANSFER`; a capability bit never substitutes for working engines.

For device identity, return the actual `registryID`, native name, `hasUnifiedMemory=YES`, truthful limits and target architecture. Keep `isHeadless=YES` for the compute-only probe; change to `NO` only when presentation exists. Do not invent an Apple GPU family/feature set to silence CA. The existing private-base/selector pattern supplies `_MTLDevice` initialization and `featureProfile`; exercise it in an owned process before CA.

## 3. Apple's IOGPU path is a different, larger contract — CACHE

This explains why the native plugin should keep HMGU rather than asking agent 6 to emulate IOGPU.

- `_IOGPUDeviceCreateWithOptions` (`IOGPU 0x1ccfad9a8`) opens the accelerator with type `1 | (options << 16)` (type 1 by default), then calls struct selector **2**, with a `0x218`-byte output/config area.
- `_IOGPUCommandQueueCreate` (`0x1ccfae4cc`) calls selector **6**, creates a notification queue, then selector **24**.
- `_IOGPUResourceCreate` (`0x1ccfa8564`) calls selector **8** and consumes the returned resource/VA/layout data.
- `_IOGPUDeviceCreateDeviceShmem` (`0x1ccfacdd4`) calls selector **12**.
- `_IOGPUCommandQueueSubmitCommandBuffers` (`0x1ccfa8b24`) uses fast trap **0** for the small case and selector **25** otherwise.
- `_IOGPUResourceCreateIOSurface` (`0x1ccfc34cc`) calls scalar selector **36** and converts the returned Mach port with `IOSurfaceLookupFromMachPort`.

That path also entails shared-memory pools, notification queues, resource residency, queue/config layout and Apple driver-specific command storage. None of those selectors is used by `HMNativeMetalDevice`: its only accelerator calls are HMGU `IOConnectCallStructMethod`, `IOConnectMapMemory64`, and unmap. **Agent 6 must not implement a guessed subset of Apple's selectors just to make the native bundle work.** Conversely, choosing Apple's `IOGPUMetalDevice` would require this whole alternative ABI and is out of scope for the minimal native path.

## 4. IOSurface allocation and GPU texture import

### 4.1 Existing IOSurface ABI is usable — CACHE plus PHYSICAL

The iOS 26 IOSurface framework matches **`IOCoreSurfaceRoot` by name**, opens type 0, calls selector 13 with a `0x28`-byte limits output, and requires `u16` at `+0x22 == 1`. Selector 0 creates from a serialized property dictionary and returns `0xc68` bytes. Lock/unlock are traps 2/3 with `(surfaceID, options, &seed)`. This exactly matches the physical int3 open/limits records and current `SweetSurface.cpp` behavior; it is not an accelerator dependency.

For the first GPU drawable require a plain, single-plane BGRA surface:

```text
IOSurfaceWidth=1125, IOSurfaceHeight=2511, IOSurfacePixelFormat='BGRA'
IOSurfaceBytesPerElement=4, IOSurfaceBytesPerRow=4608
IOSurfaceAllocSize=11583488 (= 707 * 16384)
```

The physical size is the 16-KiB-rounded allocation, not simply `bpr * height`. Start with a small 64x64 BGRA owned test, then import the real shape. Disable/avoid AGX framebuffer/IOSurface compression through the supported CA policy chosen by agent 8; never interpret AGX metadata as DXT pixels.

### 4.2 Required plugin-to-HMGU flow — DESIGN from existing SOURCE

Implement `newTextureWithDescriptor:iosurface:plane:` concretely:

1. Retain the `IOSurfaceRef`; require plane 0, plain BGRA8, supported usage, and descriptor width/height/pitch/format matching `IOSurfaceGet*`. Reject compressed, tiled, multi-plane, caller-memory, flip-slot, and unsupported private/framebuffer-only combinations explicitly.
2. Call `HMGPU_SEL_BO_IMPORT_SURFACE` with `{size, IOSurfaceGetID(surface), plane=0, flags=HMGPU_BO_CPU_CACHED}`.
3. Agent 3's kernel side authorizes the ID against the calling task's **actual registered IOSurface reference**, imports/wires the exact owned IOBuffer pages, maps them into that connection's GPU VM, and returns `{handle,gpu_va,bytes,row_bytes,format}`. Numeric ID lookup alone is not authority.
4. Validate every returned field against the descriptor/surface. The texture owns the HMGU handle and surface reference until no in-flight job can access them. Duplicate aliases share one authority/lifetime policy rather than independently unmapping the same pages.
5. `IOSurfaceLock` is not a GPU fence. CPU writes finish before native `TO_DEVICE`; only authentic engine completion plus SLC/cache handback permits `TO_CPU`, CPU lock/readback, or presentation.

Current HMGU surface code already narrows the first profile appropriately: plane 0 and cached flag only; 16-KiB size/pages; owned IOBuffer, not caller memory/flip/multi-plane; nonzero pitch/height/format; `row_bytes * height <= bytes`; per-import and client byte limits. The live 707-page surface fits the 64-MiB per-BO limit. Agent 3 must keep `hk_gpumem=2` and the surface-native authority/block/sync path enabled together with real VM mapping; enabling import without those is not readiness.

For the existing CPU-copy scanout, agent 8 can use `sweet_surface_native_present_begin/end` after GPU completion; this is a valid first correctness path but not a zero-copy/performance claim. Direct DPU scanout needs separate physical-layout and fence proof.

## 5. Minimal blit/draw route to agent 4

### 5.1 Userspace Metal objects required

Keep the current compute classes and add concrete objects using the same private-base pattern:

- `_MTLResource`-based BGRA8 texture (private BO and IOSurface-imported variants);
- `_MTLRenderPipelineState`-based linked vertex/fragment PSO;
- `_MTLCommandEncoder`-based render and blit encoders;
- queue/command-buffer support for ordered cross-engine dependencies and completion handlers.

The first public selector profile is already bounded by `validation-r3/messages.md`: `newRenderPipelineStateWithDescriptor:error:`, `newTextureWithDescriptor:`, `renderCommandEncoderWithDescriptor:`, clear/store color attachment 0, viewport/scissor, vertex/fragment buffer bindings, `drawPrimitives:vertexStart:vertexCount:`, `blitCommandEncoder`, and texture-to-shared-buffer copy with explicit destination offset, `rowBytes`, and `imageBytes`. The exact owned target is 32x24 `BGRA8Unorm`, 2D, one mip/slice/sample, color attachment 0, no depth/stencil/MSAA/blending; readback uses destination offset 256, `rowBytes=256`, `imageBytes=6144`, with the documented prefix/suffix/row guards. A 64x64 plain BGRA IOSurface is the next fixture (pitch 256, one 16-KiB allocation page). Unsupported options must mark the command buffer failed with a reason, not return a plausible stub or silently CPU-render.

For CA, add only after measurement: texture upload/sampling, source-over/premultiplied blending, offscreen attachments, function constants, IOSurface drawable textures, fences/events as actually requested. Record any unrecognized private selector and stop that profile; do not answer zero blindly.

### 5.2 Exact HMGU sequence

The transport is already defined in `hmgpu_uc.h`; no new Apple selector or wire ABI is needed:

1. `OPEN` once on the connection.
2. `BO_CREATE` for code, vertex/color data, command segments, render target and shared readback. Map CPU aliases only where that storage class requires them (shared/staging/upload/readback); a private render target need not expose CPU `contents` and is read through transfer. For a drawable use `BO_IMPORT_SURFACE` instead.
3. `CTX_CREATE` with `HMGPU_ENGINE_TRANSFER` for blit and `HMGPU_ENGINE_RENDER` for draw. `HWRT_CREATE` supplies the real render target's HWRT/free-list state; agent 4 owns validated static/firmware objects.
4. Compile/link owned AIR to validated DXT vertex/fragment USC and construct VDM/PPP/PDS streams. For a clear-only job use the declared `NO_GEOMETRY` profile; compute capability must not authorize this path.
5. `SUBMIT` a `HMGPU_JOB_RENDER` with the stream VA/bytes, HWRT handle, firmware TA/3D body sizes, and every touched BO in the read/write reference list. Agent 4 validates and patches only kernel-owned VAs, publishes work, and returns a monotonically increasing sequence.
6. For texture-to-buffer readback, `SUBMIT` a `HMGPU_JOB_TRANSFER` on the transfer context. Order it after rendering with `wait_ctx_seq` containing the render `(ctx,seq)`, then `WAIT` for the transfer sequence. A blit-only owned test uses the same transfer path without inventing render readiness.
7. Return public `Completed` only from the matching authentic completion. `WAIT/DONE` must include engine completion and cache handback before CPU bytes or IOSurface presentation are exposed. On timeout/fault/stale epoch retain all DMA resources until quiescence; `CTX_DESTROY`/`BO_DESTROY` is later.

`native/metal/runtime/src/hmn.c` demonstrates the transport discipline to reuse: mark possible publication before `SUBMIT`, validate reply sizes/sequence, pin resources on every uncertain result, and make `WAIT/DONE` the sole readback authorization. Its existing `HMGPU_SEL_*` flow is compute-only; the render/transfer implementation must not relabel that as rendering.

## 6. Implementation stages and proving log lines

All log formats below are **proposed**, not existing evidence. Include registry ID, connection, firmware epoch, context, sequence and user tag so userspace and agent 4 can be joined.

### Stage A — owned loader/compute probe

Prerequisites: clean native compute and real provider, one ready service, signed/readable bundle, process entitlement. In the controlled/headless boot, first prove the explicit-registry `HMNativeMetalBootstrap`/OPEN route from `PLAN.md` stage M1. Then have the probe call `MTLCreateSystemDefaultDevice()` and print its actual result; do not infer system-default discovery from the explicit constructor succeeding.

```text
HMNativeMetal: published class=AGXAccelerator base=IOAcceleratorES registry=<id> caps=<bits> epoch=<n> generation=<n>
HMNativeMetal: init registry=<id> connection=<n> abi=1 gpu=470002099004bc caps=<bits>
HMNativeMetal: device ready class=HMNativeMetalDevice registry=<id> headless=1
HMGU: open task=<pid> registry=<id> connection=<n> rc=0
HMNativeMetal submit connection=<n> registry=<id> tag=<tag> ctx=<ctx> seq=<seq> rc=0
HMGQ: done registry=<id> epoch=<n> ctx=<ctx> seq=<seq> engine_event=<id> cache=<id> status=DONE
```

Accept a non-nil device whose class/registry match the service and a guarded compute result with authentic done/cache evidence. If init fails, log separate `compiler`, `codesign/dlopen`, `IOServiceOpen rc`, `OPEN rc`, and `capability` reasons. Do not start CA at this stage.

### Stage B — owned blit/render probe

```text
HMNativeMetal: surface import registry=<id> surface=<id> plane=0 pages=707 bpr=4608 format=42475241 gpu_va=<va>
HMNativeMetal: submit engine=render registry=<id> ctx=<ctx> tag=<tag> seq=<seq>
HMNativeMetal: submit engine=transfer registry=<id> ctx=<ctx> wait=<renderCtx/renderSeq> tag=<tag> seq=<seq>
HMGQ: done engine=transfer registry=<id> epoch=<n> ctx=<ctx> seq=<seq> cache=<id> status=DONE
```

Accept the existing changing-color clear/triangle/quad oracle with exact pixels, input/output guards, stale-event/missing-completion controls, and a blit that is actually required for readback. A completed command with untouched poison is failure.

### Stage C — CA-facing acceptance

Only after A/B and IOSurface presentation are ready, register the CA-facing service and start backboardd/SpringBoard without the accelerator-wait skip. Require all of:

```text
IOK backboardd/SpringBoard: IOProviderClass=IOAcceleratorES -> 1 found
IOK backboardd/SpringBoard: IOProviderClass=AGXAccelerator -> AGXAccelerator
HMNativeMetal: device ready class=HMNativeMetalDevice registry=<id> headless=0
HGLTRACK: context=<actual GPU-backed class> device=HMNativeMetalDevice submit=<tag/seq> done=<engine event/seq>
```

The `SUICOrbView ... Failed to get Metal device` line must be absent, the compositor's former SWContext selection must become the GPU-backed context, and the same submission must complete before the presented IOSurface is read. Verify known glass/blur/vibrancy pixels and the owner's visual result; ordinary AppleCLCD/DPU frames remain only the scanout baseline. No new backboardd/SpringBoard abort, unrecognized selector, stale surface, or pending-DMA teardown is allowed.

## 7. Prior art — lessons and links, not code to copy

- **HakiOS Metal, commit [`9d52b514`](https://github.com/oosexgang/hakios-metal/tree/9d52b5142542a253b7263a0d7889ad278e5c7693), especially [`plugin/HakiosMetal.m`](https://github.com/oosexgang/hakios-metal/blob/9d52b5142542a253b7263a0d7889ad278e5c7693/plugin/HakiosMetal.m):** demonstrates the same discovery route (`IOAcceleratorES` → two properties → bundle → `_MTLDevice` subclass → `initWithAcceleratorPort:`), Metal private-base objects, GPU-backed buffers/queues/blit/draw, IOSurface wrapping, and eventual CoreAnimation use. **Lesson:** a custom userspace Metal driver is sufficient; implement real objects and measure known pixels. Its Adreno packets/compiler are not applicable to DXT.
- **UniXNU NativeMetal/AdrenoMetal, commit [`831a9dcb`](https://github.com/UniXNU/AdrenoMetal/commit/831a9dcbd6ac7de89a11bdaf031e07b9aadfa3c8), [`NativeAdrenoMetalPlugin.mm`](https://github.com/UniXNU/NativeMetal/blob/831a9dcbd6ac7de89a11bdaf031e07b9aadfa3c8/NativeAdrenoMetalPlugin.mm):** separates an unpublished probe from published backboardd/client devices, retains the accelerator port, uses per-process connections, and disables unsupported framebuffer/IOSurface compression. **Lesson:** stage publication and sandbox/cache work explicitly; do not test first in SpringBoard. Its Turnip/Vulkan runtime is not our DXT compiler or command path.
- **Asahi, [`Tales of the M1 GPU`](https://asahilinux.org/2022/11/tales-of-the-m1-gpu/) and [`AsahiLinux/gpu`](https://github.com/AsahiLinux/gpu):** explains the userspace compiler/command-stream versus kernel MMU/submission split and firmware-owned scheduling. **Lesson:** keep DXT stream construction in the plugin and validated VM/lifetime/submission in HMGU. AGX/RTKit/IOGPU details do not transfer to PowerVR, and Asahi is not a Metal plugin implementation.

No virtio-gpu-Metal shortcut was found that removes the need for a real `_MTLDevice` implementation and GPU backend. Translation/prior-art success on Adreno or AGX is architectural evidence only, not DXT execution evidence.

## 8. Risks and stop rules

| Risk | Mitigation / stop |
|---|---|
| Property-only publication | Stop unless the readiness lease covers firmware epoch, VM/context, validated streams, engine completion and cache handback. |
| Two Metal services | Suppress bare/duplicate accelerators; default-device count must be one. |
| Compiler or signing mistaken for registry failure | Log each init stage. No production publication without the real provider and loadable signed bundle. |
| HMGU permission failure | Supply the process entitlement or reviewed authorization; never silently grant every task. |
| Compute-only device exposed to CA | Keep CA registration off until concrete render/transfer/IOSurface selectors pass owned tests. |
| Guessed IOGPU selectors | Use HMGU only. Stop any design that requires partial `MTLIOAccelDevice` emulation without a separate full ABI investigation. |
| Unsupported CA selector | Fail explicitly and capture selector/stack; no zero forwarding, fake family/capability, or CPU production renderer. |
| IOSurface ID confused with authority | Authorize the caller's registered ref, retain surface/BO/pages through actual completion/quiescence, reject aliases that violate that policy. |
| Cache/lock mistaken for completion | `IOSurfaceLock`, cache flush, KCCB consumption, API `Completed`, and DPU frames are individually insufficient. Require engine DONE + cache handback before CPU/DPU reads. |
| Timeout reclamation | Keep BOs, contexts, mappings and surfaces pinned until real DMA quiescence; never free on timeout alone. |
| False hardware-context acceptance | Join HGLTRACK device/context to agent 4 submit/done and known presented pixels. Do not merely suppress SWContext or the SUICOrbView message. |

## 9. Needs from other owners and requested live probe

- **Agent 6 (IOAccel):** implement the single derived `AGXAccelerator`/`IOAcceleratorES` service, exact properties, HMGU `newUserClient`, readiness-gated early registration, and no duplicate bare service. Publish the proposed registry/epoch/caps line.
- **Agent 3 (MMU/IOSurface):** provide authorized plane-0 BGRA import, 16-KiB page array and real VM mapping, alias/lifetime rules, native block/sync handback, and the 707-page live-shape check. Confirm no caller-memory/flip/compressed surface is admitted.
- **Agent 4 (command path):** implement genuine transfer/render contexts, HWRT, validated VDM/PPP/PDS/CDM streams as applicable, cross-engine `wait_ctx_seq`, and engine+cache completion records joined to `(registry,epoch,ctx,seq)`.
- **Agent 8 (compositor):** choose plain BGRA/no unsupported compression, extend HGLTRACK with actual context/device/submit/done, and fence IOSurface presentation after GPU completion. Initial CPU-copy presentation is acceptable only with that fence and no performance claim.
- **Agent 10 (integration):** stage the production compiler/provider and signed bundle, process entitlements, remove `HK_ACCEL_ONCE=skip`, and sequence owned probes before CA. Use `hk_ustack=backboardd,SpringBoard` as specified in `LIVE-EVIDENCE.md` when CA begins.

**Requested live probe (only after those prerequisites):** in a controlled/headless boot, one owned process first succeeds through explicit-registry bootstrap/OPEN, then calls `MTLCreateSystemDefaultDevice()` and prints class/name/registry/headless, creates a queue, performs a guarded compute and transfer blit, creates a 64x64 plain BGRA IOSurface, imports it through HMGU, renders/clears known colors, reads them back, then repeats with the 1125x2511/4608/11583488 shape. Capture every line in §6 plus IOKit service properties and any `IOServiceOpen`/`OPEN` return code. Do not boot SpringBoard against the device until this probe and the render oracle pass; the later CA boot must show the SUICOrbView failure gone and the correlated GPU-backed HGLTRACK context, not just registry matches.
