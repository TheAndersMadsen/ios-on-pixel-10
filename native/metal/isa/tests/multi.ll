; SPDX-License-Identifier: MIT
; Copyright (c) 2026 hackios contributors. Original three-buffer scalar graph.
; AIR metadata syntax follows immutable MIT air-r2/tests/prepare.py. Host test
; fixture only; no LLVM executable/subprocess is used by the runtime compiler.
target datalayout = "e-p:64:64:64-i64:64-f32:32:32-n8:16:32"
target triple = "air64_v28-apple-ios26.0.0"
define void @multi(ptr addrspace(1) readonly %a, ptr addrspace(1) readonly %b, ptr addrspace(1) writeonly %out) {
 %pa = getelementptr inbounds float, ptr addrspace(1) %a, i64 1
 %x = load float, ptr addrspace(1) %pa, align 4
 %pb = getelementptr inbounds float, ptr addrspace(1) %b, i64 2
 %y = load float, ptr addrspace(1) %pb, align 4
 %z = fsub float %x, %y
 %pout = getelementptr inbounds float, ptr addrspace(1) %out, i64 3
 store float %z, ptr addrspace(1) %pout, align 4
 ret void
}
!air.version = !{!0}
!air.kernel = !{!1}
!air.compile_options = !{!5,!6}
!0 = !{i32 2,i32 8,i32 0}
!1 = !{ptr @multi,!2,!3}
!2 = !{}
!3 = !{!4,!7,!8}
!4 = !{i32 0,!"air.buffer",!"air.location_index",i32 0,i32 1,!"air.read",!"air.address_space",i32 1,!"air.arg_type_size",i32 4,!"air.arg_type_align_size",i32 4,!"air.arg_type_name",!"float",!"air.arg_name",!"a"}
!5 = !{!"air.compile.fast_math_disable"}
!6 = !{!"air.compile.denorms_disable"}
!7 = !{i32 1,!"air.buffer",!"air.location_index",i32 1,i32 1,!"air.read",!"air.address_space",i32 1,!"air.arg_type_size",i32 4,!"air.arg_type_align_size",i32 4,!"air.arg_type_name",!"float",!"air.arg_name",!"b"}
!8 = !{i32 2,!"air.buffer",!"air.location_index",i32 2,i32 1,!"air.write",!"air.address_space",i32 1,!"air.arg_type_size",i32 4,!"air.arg_type_align_size",i32 4,!"air.arg_type_name",!"float",!"air.arg_name",!"out"}
