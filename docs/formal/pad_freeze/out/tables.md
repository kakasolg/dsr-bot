
### 성질

| 실행 (성질 · 스크립트 · 호출 상한 · 설정) | current | block | ownerNeutral | both | minimal |
|---|---|---|---|---|---|
| S1_MenuClean · quit · m3 | **위반** 1,667 (trace 5) | **위반** 1,089 (trace 4) | 성립 316,881 | 성립 70,834 | 성립 53,785 |
| S1b_MenuNoB · quit · m3 | **위반** 1,369 (trace 4) | 성립 69,871 | 성립 316,881 | 성립 70,834 | 성립 53,785 |
| S3_Handoff · quit · m3 | 성립 637,758 | 성립 69,871 | 성립 316,881 | 성립 70,834 | 성립 53,785 |
| S4_ReSprint · quit · m3 | **위반** 3,384 (trace 6) | 성립 69,871 | **위반** 4,177 (trace 6) | 성립 70,834 | 성립 53,785 |
| S4_ReGuard · quit · m3 | 성립 637,758 | 성립 69,871 | 성립 316,881 | 성립 70,834 | 성립 53,785 |
| S5_StaleNoKill · quit · m3 | 성립 637,758 | 성립 69,871 | 성립 316,881 | 성립 70,834 | 성립 53,785 |
| S6_NoOrphanLB · quit · m3 | **위반** 3,853 (trace 7) | **위반** 3,239 (trace 5) | **위반** 4,785 (trace 5) | **위반** 3,328 (trace 8) | **위반** 2,418 (trace 5) |
| S6_NoOrphanLB · quit · m3 · noguard | **위반** 3,018 (trace 6) | 성립 30,824 | 성립 140,905 | 성립 31,745 | 성립 24,920 |
| S6_post · quit · m3 · noguard | **위반** 13,422 (trace 10) | 성립 30,824 | 성립 140,905 | 성립 31,745 | 성립 24,920 |
| S2_NoOrphanA · tapper · m3 | **위반** 1,894 (trace 5) | 성립 98,527 | **위반** 3,224 (trace 5) | 성립 104,641 | 성립 72,757 |
| S5_StaleNoKill · tapper · m3 | 성립 694,660 | 성립 98,527 | 성립 456,982 | 성립 104,641 | 성립 72,757 |
| S1_MenuClean · quit · m4 | **위반** 1,364 (trace 6) | **위반** 1,624 (trace 4) | 성립 1,182,771 | 성립 247,331 | 성립 198,807 |
| S1b_MenuNoB · quit · m4 | **위반** 1,426 (trace 4) | 성립 239,045 | 성립 1,182,771 | 성립 247,331 | 성립 198,807 |
| S3_Handoff · quit · m4 | 성립 2,382,891 | 성립 239,045 | 성립 1,182,771 | 성립 247,331 | 성립 198,807 |
| S4_ReSprint · quit · m4 | **위반** 4,364 (trace 6) | 성립 239,045 | **위반** 2,772 (trace 9) | 성립 247,331 | 성립 198,807 |
| S4_ReGuard · quit · m4 | 성립 2,382,891 | 성립 239,045 | 성립 1,182,771 | 성립 247,331 | 성립 198,807 |
| S5_StaleNoKill · quit · m4 | 성립 2,382,891 | 성립 239,045 | 성립 1,182,771 | 성립 247,331 | 성립 198,807 |
| S6_NoOrphanLB · quit · m4 | **위반** 3,621 (trace 6) | **위반** 3,200 (trace 8) | **위반** 4,102 (trace 5) | **위반** 3,530 (trace 5) | **위반** 3,514 (trace 5) |
| S6_NoOrphanLB · quit · m4 · noguard | **위반** 3,458 (trace 6) | 성립 85,783 | 성립 395,779 | 성립 89,213 | 성립 73,069 |
| S6_post · quit · m4 · noguard | **위반** 21,048 (trace 11) | 성립 85,783 | 성립 395,779 | 성립 89,213 | 성립 73,069 |
| S2_NoOrphanA · tapper · m4 | **위반** 2,652 (trace 6) | 성립 306,163 | **위반** 3,083 (trace 6) | 성립 330,137 | 성립 241,897 |
| S5_StaleNoKill · tapper · m4 | 성립 2,478,509 | 성립 306,163 | 성립 1,617,135 | 성립 330,137 | 성립 241,897 |
| S5_StaleNoKill · quit · m3 · hold | **위반** 7,222 (trace 5) | **위반** 4,570 (trace 5) | **위반** 9,556 (trace 6) | **위반** 5,249 (trace 6) | **위반** 3,592 (trace 6) |
| S5f_FrozenDueNoKill · quit · m3 · hold | **위반** 26,765 (trace 8) | 성립 82,565 | **위반** 25,021 (trace 11) | 성립 85,640 | 성립 65,126 |
| S5f_FrozenDueNoKill · quit · m4 · hold | **위반** 37,361 (trace 8) | 성립 309,958 | **위반** 22,012 (trace 8) | 성립 329,710 | 성립 261,469 |
| S5_StaleNoKill · tapper · m3 · hold | **위반** 8,196 (trace 6) | **위반** 4,701 (trace 5) | **위반** 10,358 (trace 8) | **위반** 4,026 (trace 10) | **위반** 3,683 (trace 5) |
| S5f_FrozenDueNoKill · tapper · m3 · hold | **위반** 50,365 (trace 8) | 성립 119,928 | **위반** 33,566 (trace 8) | 성립 128,781 | 성립 91,814 |
| S5f_FrozenDueNoKill · tapper · m4 · hold | **위반** 37,426 (trace 8) | 성립 420,365 | **위반** 22,201 (trace 8) | 성립 458,131 | 성립 342,705 |

### 도달 탐침

| 실행 (성질 · 스크립트 · 호출 상한 · 설정) | current | block | ownerNeutral | both | minimal |
|---|---|---|---|---|---|
| R1_menuAfterBlockedCall · quit · m3 | **위반** 501 (trace 4) | **위반** 174 (trace 4) | **위반** 383 (trace 4) | **위반** 230 (trace 5) | **위반** 412 (trace 5) |
| R1_menuWithKeep · quit · m3 | **위반** 663 (trace 4) | **위반** 1,775 (trace 4) | **위반** 908 (trace 5) | **위반** 2,783 (trace 4) | 성립 53,785 |
| R1_menuWithYoungB · quit · m3 | **위반** 500 (trace 5) | 성립 69,871 | **위반** 446 (trace 5) | 성립 70,834 | 성립 53,785 |
| R3_nudgeUnfreezeLate · quit · m3 | **위반** 1,326 (trace 4) | **위반** 862 (trace 4) | **위반** 1,223 (trace 4) | **위반** 670 (trace 4) | **위반** 873 (trace 4) |
| R4_resprintAfterQuit · quit · m3 | **위반** 3,372 (trace 9) | **위반** 2,894 (trace 9) | **위반** 5,636 (trace 9) | **위반** 2,612 (trace 9) | **위반** 2,038 (trace 9) |
| R4_reguardAfterQuit · quit · m3 | **위반** 4,130 (trace 9) | **위반** 3,444 (trace 9) | **위반** 6,399 (trace 9) | **위반** 2,122 (trace 9) | **위반** 3,411 (trace 10) |
| R5_newerPressRipe · quit · m3 | **위반** 3,213 (trace 6) | 성립 69,871 | **위반** 4,150 (trace 7) | 성립 70,834 | 성립 53,785 |
| R6_afterQuitWithKeep · quit · m3 · noguard | **위반** 3,018 (trace 8) | **위반** 2,675 (trace 9) | **위반** 3,835 (trace 8) | **위반** 1,790 (trace 9) | **위반** 2,049 (trace 9) |
| R2_ripeAWhileFrozen · tapper · m3 | **위반** 437 (trace 5) | **위반** 345 (trace 5) | **위반** 772 (trace 5) | **위반** 639 (trace 5) | **위반** 347 (trace 5) |
| R5_newerPressRipe · tapper · m3 | **위반** 1,047 (trace 7) | **위반** 1,155 (trace 6) | **위반** 1,322 (trace 5) | **위반** 714 (trace 5) | **위반** 940 (trace 5) |
| R5_newerPressRipe · quit · m3 · hold | **위반** 3,429 (trace 7) | **위반** 3,079 (trace 4) | **위반** 2,950 (trace 7) | **위반** 3,233 (trace 5) | **위반** 2,553 (trace 5) |
| R5_newerPressRipe · tapper · m3 · hold | **위반** 1,404 (trace 5) | **위반** 1,024 (trace 5) | **위반** 1,081 (trace 5) | **위반** 933 (trace 5) | **위반** 577 (trace 6) |

실행 200회, 정상 완료 아님(ERROR/TYPE-ERROR) 0회
