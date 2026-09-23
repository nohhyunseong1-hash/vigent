#!/usr/bin/env python3
"""loaded_crt.py — torch import 후 **실제로 로드된** CRT DLL 의 경로·버전을 찍는다. [I-4]

★왜 필요한가
  포터블은 `python\\` 에 `vcruntime140.dll`·`vcruntime140_1.dll`(14.38.33126.1)을 **동봉**한다.
  그런데 torch/cuDNN 구성요소의 빌드툴 버전은 **14.44** 다(PE 링커 버전 실측).
  Microsoft 규칙("재배포 버전은 구성요소 최신 빌드툴 이상")대로면 **14.38 동봉본이 먼저 로드되면
  요구를 못 맞춘다.** 설정이 아니라 **실제 로드 경로**를 봐야 알 수 있다.

Windows 는 기본적으로 **실행 파일이 있는 디렉터리**를 System32 보다 먼저 찾는다
(SafeDllSearchMode). 그래서 python.exe 옆의 동봉본이 이길 가능성이 높다 — 확인한다.

사용: <포터블>\\python\\python.exe scripts\\bench\\loaded_crt.py
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys

TARGETS = ["vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll",
           "msvcp140_atomic_wait.dll", "msvcp140_1.dll", "concrt140.dll"]


def loaded_modules() -> list[tuple[str, str]]:
    """현재 프로세스에 로드된 모듈의 (이름, 전체경로).

    ★argtypes/restype 를 반드시 지정한다. 지정하지 않으면 64비트에서 HANDLE/HMODULE 이
      c_int 로 잘려 EnumProcessModules 가 조용히 실패하고 **빈 목록**이 나온다
      (2026-09-23 실제로 그렇게 나와서 "CRT 가 하나도 로드 안 됨" 이라는 말이 안 되는
      결과를 봤다 — 규칙 11 로 잡았다).
    """
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wt.HANDLE
    k32.GetCurrentProcess.argtypes = []
    psapi.EnumProcessModulesEx.restype = wt.BOOL
    psapi.EnumProcessModulesEx.argtypes = [wt.HANDLE, ctypes.POINTER(wt.HMODULE), wt.DWORD,
                                           ctypes.POINTER(wt.DWORD), wt.DWORD]
    psapi.GetModuleFileNameExW.restype = wt.DWORD
    psapi.GetModuleFileNameExW.argtypes = [wt.HANDLE, wt.HMODULE, wt.LPWSTR, wt.DWORD]

    h = k32.GetCurrentProcess()
    cap = 4096
    arr = (wt.HMODULE * cap)()
    need = wt.DWORD()
    LIST_MODULES_ALL = 0x03
    if not psapi.EnumProcessModulesEx(h, arr, ctypes.sizeof(arr), ctypes.byref(need), LIST_MODULES_ALL):
        raise SystemExit(f"EnumProcessModulesEx 실패: GetLastError={ctypes.get_last_error()}")
    n = min(need.value // ctypes.sizeof(wt.HMODULE), cap)
    out = []
    buf = ctypes.create_unicode_buffer(32768)
    for i in range(n):
        if psapi.GetModuleFileNameExW(h, arr[i], buf, len(buf)):
            p = buf.value
            out.append((p.rsplit("\\", 1)[-1].lower(), p))
    if not out:
        raise SystemExit("모듈을 하나도 못 읽었다 — 열거 실패로 본다(0건은 성공이 아니다)")
    return out


def file_version(path: str) -> str:
    """파일 버전(예: 14.38.33126.1). 실패하면 빈 문자열."""
    ver = ctypes.WinDLL("version", use_last_error=True)
    size = ver.GetFileVersionInfoSizeW(path, None)
    if not size:
        return ""
    buf = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(path, 0, size, buf):
        return ""
    p = ctypes.c_void_p()
    ln = ctypes.c_uint()
    if not ver.VerQueryValueW(buf, "\\", ctypes.byref(p), ctypes.byref(ln)):
        return ""

    class FFI(ctypes.Structure):
        _fields_ = [("dwSignature", ctypes.c_uint), ("dwStrucVersion", ctypes.c_uint),
                    ("dwFileVersionMS", ctypes.c_uint), ("dwFileVersionLS", ctypes.c_uint),
                    ("dwProductVersionMS", ctypes.c_uint), ("dwProductVersionLS", ctypes.c_uint),
                    ("dwFileFlagsMask", ctypes.c_uint), ("dwFileFlags", ctypes.c_uint),
                    ("dwFileOS", ctypes.c_uint), ("dwFileType", ctypes.c_uint),
                    ("dwFileSubtype", ctypes.c_uint), ("dwFileDateMS", ctypes.c_uint),
                    ("dwFileDateLS", ctypes.c_uint)]
    f = ctypes.cast(p, ctypes.POINTER(FFI)).contents
    return "{}.{}.{}.{}".format(f.dwFileVersionMS >> 16, f.dwFileVersionMS & 0xFFFF,
                                f.dwFileVersionLS >> 16, f.dwFileVersionLS & 0xFFFF)


print("=== import 전 ===")
before = {n: p for n, p in loaded_modules() if n in TARGETS}
for n in TARGETS:
    if n in before:
        print(f"  {n:<28} {file_version(before[n]):<18} {before[n]}")

print("\n=== torch import + CUDA 초기화 후 ===")
import torch  # noqa: E402

print(f"  torch {torch.__version__} · cuda_available={torch.cuda.is_available()}")
if torch.cuda.is_available():
    torch.zeros(8, device="cuda")

after = {n: p for n, p in loaded_modules() if n in TARGETS}
sysroot = (sys.prefix or "").lower()
verdict = []
for n in TARGETS:
    if n not in after:
        print(f"  {n:<28} (로드 안 됨)")
        continue
    p = after[n]
    v = file_version(p)
    where = "★동봉(포터블 python\\)" if "\\python\\" in p.lower() and "system32" not in p.lower() else (
        "시스템(System32)" if "system32" in p.lower() else "기타")
    print(f"  {n:<28} {v:<18} {where:<22} {p}")
    verdict.append((n, v, where))

print("\n=== 판정 ===")
NEED = (14, 44)     # torch/cuDNN 구성요소 최신 빌드툴(실측). MS 이진호환 규칙의 하한.
bad = []
for n, v, where in verdict:
    try:
        mm = tuple(int(x) for x in v.split(".")[:2])
    except Exception:  # noqa: BLE001
        continue
    if mm < NEED:
        bad.append(f"{n} {v} ({where})")
if bad:
    print(f"  ★하한(14.44) 미만으로 로드된 것: {', '.join(bad)}")
else:
    print("  로드된 CRT 는 모두 14.44 이상")
