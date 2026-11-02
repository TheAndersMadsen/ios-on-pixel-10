; SPDX-License-Identifier: MIT
; Copyright (c) 2026 hackios contributors.
; Original owned ALU liveness test. AIR metadata shape follows immutable MIT
; air-r2/tests/prepare.py; compiled ONLY by host test preparation, not runtime.
target datalayout = "e-p:64:64:64-i64:64-f32:32:32-n8:16:32"
target triple = "air64_v28-apple-ios26.0.0"
define void @test(ptr addrspace(1) %v) {
 %a = load float, ptr addrspace(1) %v, align 4
 %p = getelementptr inbounds float, ptr addrspace(1) %v, i64 1
 %b = load float, ptr addrspace(1) %p, align 4
 %sum = fadd float %a, %b
 %difference = fsub float %sum, %a
 %product = fmul float %difference, %b
 %q = getelementptr inbounds float, ptr addrspace(1) %v, i64 2
 store float %product, ptr addrspace(1) %q, align 4
 ret void
}
!air.version = !{!0}
!air.kernel = !{!1}
!air.compile_options = !{!5,!6}
!0 = !{i32 2,i32 8,i32 0}
!1 = !{ptr @test,!2,!3}
!2 = !{}
!3 = !{!4}
!4 = !{i32 0,!"air.buffer",!"air.location_index",i32 0,i32 1,!"air.read_write",!"air.address_space",i32 1,!"air.arg_type_size",i32 4,!"air.arg_type_align_size",i32 4,!"air.arg_type_name",!"float",!"air.arg_name",!"v"}
!5 = !{!"air.compile.fast_math_disable"}
!6 = !{!"air.compile.denorms_disable"}
