# Notes

## LLVM dependence output (T2.1)
How to get it: compile a loop to IR with -g, then run
    opt -passes='print<access-info>' -disable-output file.ll
Write here what the output looks like and how to map it to line and column.

## Findings / dead ends
