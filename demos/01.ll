; ModuleID = 'remarks/test1.cpp'
source_filename = "remarks/test1.cpp"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: mustprogress noinline nounwind uwtable
define dso_local void @_Z3addPfPKfS1_i(ptr noalias noundef %0, ptr noalias noundef %1, ptr noalias noundef %2, i32 noundef %3) #0 !dbg !10 {
  %5 = alloca ptr, align 8
  %6 = alloca ptr, align 8
  %7 = alloca ptr, align 8
  %8 = alloca i32, align 4
  %9 = alloca i32, align 4
  store ptr %0, ptr %5, align 8
    #dbg_declare(ptr %5, !21, !DIExpression(), !22)
  store ptr %1, ptr %6, align 8
    #dbg_declare(ptr %6, !23, !DIExpression(), !24)
  store ptr %2, ptr %7, align 8
    #dbg_declare(ptr %7, !25, !DIExpression(), !26)
  store i32 %3, ptr %8, align 4
    #dbg_declare(ptr %8, !27, !DIExpression(), !28)
    #dbg_declare(ptr %9, !29, !DIExpression(), !31)
  store i32 0, ptr %9, align 4, !dbg !31
  br label %10, !dbg !32

10:                                               ; preds = %30, %4
  %11 = load i32, ptr %9, align 4, !dbg !33
  %12 = load i32, ptr %8, align 4, !dbg !35
  %13 = icmp slt i32 %11, %12, !dbg !36
  br i1 %13, label %14, label %33, !dbg !37

14:                                               ; preds = %10
  %15 = load ptr, ptr %6, align 8, !dbg !38
  %16 = load i32, ptr %9, align 4, !dbg !39
  %17 = sext i32 %16 to i64, !dbg !38
  %18 = getelementptr inbounds float, ptr %15, i64 %17, !dbg !38
  %19 = load float, ptr %18, align 4, !dbg !38
  %20 = load ptr, ptr %7, align 8, !dbg !40
  %21 = load i32, ptr %9, align 4, !dbg !41
  %22 = sext i32 %21 to i64, !dbg !40
  %23 = getelementptr inbounds float, ptr %20, i64 %22, !dbg !40
  %24 = load float, ptr %23, align 4, !dbg !40
  %25 = fadd float %19, %24, !dbg !42
  %26 = load ptr, ptr %5, align 8, !dbg !43
  %27 = load i32, ptr %9, align 4, !dbg !44
  %28 = sext i32 %27 to i64, !dbg !43
  %29 = getelementptr inbounds float, ptr %26, i64 %28, !dbg !43
  store float %25, ptr %29, align 4, !dbg !45
  br label %30, !dbg !43

30:                                               ; preds = %14
  %31 = load i32, ptr %9, align 4, !dbg !46
  %32 = add nsw i32 %31, 1, !dbg !46
  store i32 %32, ptr %9, align 4, !dbg !46
  br label %10, !dbg !47, !llvm.loop !48

33:                                               ; preds = %10
  ret void, !dbg !51
}

attributes #0 = { mustprogress noinline nounwind uwtable "frame-pointer"="all" "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!2, !3, !4, !5, !6, !7, !8}
!llvm.ident = !{!9}

!0 = distinct !DICompileUnit(language: DW_LANG_C_plus_plus_14, file: !1, producer: "Ubuntu clang version 22.1.8 (++20260714015917+ca7933e47d3a-1~exp1~20260714135927.17)", isOptimized: false, runtimeVersion: 0, emissionKind: FullDebug, splitDebugInlining: false, nameTableKind: None)
!1 = !DIFile(filename: "remarks/test1.cpp", directory: "/home/meghss/project/demos", checksumkind: CSK_MD5, checksum: "9b98be7bc33a53abaeb5921f3b0d20e9")
!2 = !{i32 7, !"Dwarf Version", i32 5}
!3 = !{i32 2, !"Debug Info Version", i32 3}
!4 = !{i32 1, !"wchar_size", i32 4}
!5 = !{i32 8, !"PIC Level", i32 2}
!6 = !{i32 7, !"PIE Level", i32 2}
!7 = !{i32 7, !"uwtable", i32 2}
!8 = !{i32 7, !"frame-pointer", i32 2}
!9 = !{!"Ubuntu clang version 22.1.8 (++20260714015917+ca7933e47d3a-1~exp1~20260714135927.17)"}
!10 = distinct !DISubprogram(name: "add", linkageName: "_Z3addPfPKfS1_i", scope: !1, file: !1, line: 3, type: !11, scopeLine: 3, flags: DIFlagPrototyped, spFlags: DISPFlagDefinition, unit: !0, retainedNodes: !20)
!11 = !DISubroutineType(types: !12)
!12 = !{null, !13, !16, !16, !19}
!13 = !DIDerivedType(tag: DW_TAG_restrict_type, baseType: !14)
!14 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !15, size: 64)
!15 = !DIBasicType(name: "float", size: 32, encoding: DW_ATE_float)
!16 = !DIDerivedType(tag: DW_TAG_restrict_type, baseType: !17)
!17 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !18, size: 64)
!18 = !DIDerivedType(tag: DW_TAG_const_type, baseType: !15)
!19 = !DIBasicType(name: "int", size: 32, encoding: DW_ATE_signed)
!20 = !{}
!21 = !DILocalVariable(name: "a", arg: 1, scope: !10, file: !1, line: 3, type: !13)
!22 = !DILocation(line: 3, column: 28, scope: !10)
!23 = !DILocalVariable(name: "b", arg: 2, scope: !10, file: !1, line: 3, type: !16)
!24 = !DILocation(line: 3, column: 55, scope: !10)
!25 = !DILocalVariable(name: "c", arg: 3, scope: !10, file: !1, line: 3, type: !16)
!26 = !DILocation(line: 3, column: 82, scope: !10)
!27 = !DILocalVariable(name: "n", arg: 4, scope: !10, file: !1, line: 3, type: !19)
!28 = !DILocation(line: 3, column: 89, scope: !10)
!29 = !DILocalVariable(name: "i", scope: !30, file: !1, line: 4, type: !19)
!30 = distinct !DILexicalBlock(scope: !10, file: !1, line: 4, column: 3)
!31 = !DILocation(line: 4, column: 12, scope: !30)
!32 = !DILocation(line: 4, column: 8, scope: !30)
!33 = !DILocation(line: 4, column: 19, scope: !34)
!34 = distinct !DILexicalBlock(scope: !30, file: !1, line: 4, column: 3)
!35 = !DILocation(line: 4, column: 23, scope: !34)
!36 = !DILocation(line: 4, column: 21, scope: !34)
!37 = !DILocation(line: 4, column: 3, scope: !30)
!38 = !DILocation(line: 5, column: 12, scope: !34)
!39 = !DILocation(line: 5, column: 14, scope: !34)
!40 = !DILocation(line: 5, column: 19, scope: !34)
!41 = !DILocation(line: 5, column: 21, scope: !34)
!42 = !DILocation(line: 5, column: 17, scope: !34)
!43 = !DILocation(line: 5, column: 5, scope: !34)
!44 = !DILocation(line: 5, column: 7, scope: !34)
!45 = !DILocation(line: 5, column: 10, scope: !34)
!46 = !DILocation(line: 4, column: 27, scope: !34)
!47 = !DILocation(line: 4, column: 3, scope: !34)
!48 = distinct !{!48, !37, !49, !50}
!49 = !DILocation(line: 5, column: 22, scope: !30)
!50 = !{!"llvm.loop.mustprogress"}
!51 = !DILocation(line: 6, column: 1, scope: !10)
