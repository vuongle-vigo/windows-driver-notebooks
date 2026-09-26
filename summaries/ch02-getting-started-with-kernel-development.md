# Chương 2: Getting Started with Kernel Development

> Nguồn: *Windows Kernel Programming, 2nd Edition* — Pavel Yosifovich, trang 28–38

## Tổng quan

Chương này cung cấp nền tảng để bắt đầu lập trình driver kernel: cài công cụ, tạo project bằng Visual Studio + WDK, viết driver tối giản với `DriverEntry` và Unload routine, cài đặt/nạp driver bằng `sc.exe`, và trace bằng `DbgPrint`/`KdPrint` với Sysinternals DebugView — chứng minh chuỗi công cụ hoạt động trước khi vào khái niệm kernel sâu hơn.

## Nội dung theo từng mục

### Installing the Tools
- Trước 2012, build driver phải dùng công cụ build riêng của DDK, không có IDE tích hợp; từ Visual Studio 2012 + WDK 8, Microsoft chính thức hỗ trợ build driver trong Visual Studio (msbuild).
- Cài theo thứ tự: (1) Visual Studio 2019 mới nhất, workload C++ bắt buộc (SKU nào cũng được, gồm Community miễn phí); (2) Windows 11 SDK, chọn ít nhất Debugging Tools for Windows; (3) Windows 11 WDK — build được cho Windows 7 trở lên, wizard phải cài project template cho Visual Studio; (4) Sysinternals Suite, tải miễn phí từ sysinternals.com, giải nén là dùng.
- Phiên bản SDK và WDK phải khớp nhau; kiểm tra template bằng cách mở New Project và tìm "Empty WDM Driver".

### Creating a Driver Project
- Tạo project từ template "WDM Empty Driver", ví dụ đặt tên "Sample".
- Xóa file `Sample.inf` trong filter "Driver Files" — ví dụ này không cần.
- Thêm C++ source file tên `Sample.cpp` vào node Source Files.

### The DriverEntry and Unload Routines
- `DriverEntry` là entry point mặc định, coi như "main" của driver; được một system thread gọi ở `IRQL PASSIVE_LEVEL` (0) — IRQL chi tiết ở chương 8.
- Prototype cố định: nhận `PDRIVER_OBJECT` và `PUNICODE_STRING RegistryPath` (đường dẫn registry của driver), trả về `NTSTATUS`. Chú thích `_In_` thuộc SAL (Source Code Annotation Language): vô hình với compiler, cung cấp metadata cho static analysis — nên dùng whenever possible.
- Ba vấn đề compile tuần tự: (1) cần `#include <ntddk.h>` để có định nghĩa kiểu; (2) compiler mặc định treat warnings as errors — không nên tắt vì warning có thể là error ngụy trang; dùng macro `UNREFERENCED_PARAMETER` (chỉ "viết ra" giá trị tham số để nó được tính là đã tham chiếu) hoặc bỏ tên tham số; (3) `DriverEntry` phải có C-linkage nên khi build bằng C++ phải thêm `extern "C"`, nếu không linker error.
- Mọi thứ làm trong `DriverEntry` phải được hoàn tác khi unload, nếu không sẽ leak và kernel không dọn cho đến lần reboot kế tiếp. Đăng ký Unload routine bằng `DriverObject->DriverUnload = SampleUnload;` — routine nhận lại driver object, trả về `void`; driver mẫu chưa cấp phát gì nên để trống.

### Deploying the Driver
- Nên cài và nạp driver trên máy ảo để loại trừ rủi ro crash máy chính.
- Cài driver phần mềm giống cài service user-mode: gọi API `CreateService` hoặc công cụ tương đương — sách dùng `Sc.exe` (Service Control) tích hợp sẵn; đây là privileged operation, chạy trong elevated command window với quyền administrator.
- Tạo service: `sc create sample type= kernel binPath= c:\dev\sample\x64\debug\sample.sys` — không có khoảng trắng giữa tên tùy chọn và dấu bằng, nhưng có khoảng trắng sau dấu bằng; kiểm tra kết quả trong registry tại `HKLM\System\CurrentControlSet\Services\Sample`.
- Nạp bằng `sc start sample` (gọi API `StartService`); hệ 64-bit yêu cầu driver được ký nên lệnh thường thất bại.
- Giải pháp khi develop: `bcdedit /set testsigning on` (cần reboot mới hiệu lực). Trên Windows 10+ có Secure Boot, việc đổi test signing sẽ thất bại (local kernel debugging cũng được bảo vệ); không tắt được Secure Boot qua BIOS thì test trên máy ảo. Với target trước Windows 10, phải đặt Target OS version trong project properties (all configurations/all platforms).
- Nạp thành công: `STATE: 4 RUNNING (STOPPABLE, NOT_PAUSABLE, IGNORES_SHUTDOWN)`; xác nhận bằng Process Explorer thấy `Sample.Sys` trong system space. Gỡ bằng `sc stop sample` — sc.exe gọi `ControlService` với `SERVICE_CONTROL_STOP`, khiến Unload routine chạy.

### Simple Tracing
- `DbgPrint` in text kiểu printf, xem được qua kernel debugger hoặc công cụ khác; vì có overhead nên dùng `KdPrint` — macro chỉ được compile trong Debug build rồi gọi `DbgPrint` bên dưới.
- `KdPrint` phải viết với ngoặc đôi `KdPrint(("..."))`: macro không nhận được số tham số biến đổi, nên dùng mẹo compiler truyền cả format string lẫn đối số như một tham số duy nhất.
- Xem output bằng Sysinternals DebugView (`DbgView.exe`, chạy elevated): bật Capture Kernel (Ctrl+K), tắt Capture Win32/Global Win32 để output user-mode không làm rối.
- Từ Windows Vista, output `DbgPrint` không được sinh ra trừ khi tạo registry key `Debug Print Filter` dưới `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager`, DWORD `DEFAULT` = 8 (mọi giá trị có bit 3 set đều được), rồi restart. Tùy chọn Enable Verbose Kernel Output của DebugView bỏ qua được thiết lập này nhưng dường như không hoạt động trên Windows 11.
- Bài tập cuối chương: in phiên bản Windows (major, minor, build number) từ `DriverEntry` bằng `RtlGetVersion`, kiểm chứng bằng DebugView.

## API / cấu trúc / hằng số quan trọng

| Tên | Loại | Vai trò & ghi chú ngắn |
|---|---|---|
| `DriverEntry` | hàm | Entry point mặc định, chạy ở `PASSIVE_LEVEL`, trả `NTSTATUS` |
| `DriverUnload` | thành viên `DRIVER_OBJECT` | Con trỏ tới Unload routine, tự chạy trước khi driver bị nạp ra |
| `PDRIVER_OBJECT` / `PUNICODE_STRING` | struct (con trỏ) | Driver object / đường dẫn registry truyền vào `DriverEntry` |
| `NTSTATUS` / `STATUS_SUCCESS` | kiểu / hằng số | Mã trạng thái; báo khởi tạo thành công |
| `_In_` (SAL) | annotation | Metadata cho static analysis, trong suốt với compiler |
| `UNREFERENCED_PARAMETER` | macro | "Tham chiếu" tham số không dùng để tránh warning-as-error |
| `ntddk.h` | header | Định nghĩa kiểu cơ bản của kernel API |
| `DbgPrint` | hàm | In text kiểu printf ra kernel debug output; có overhead |
| `KdPrint` | macro | Chỉ compile trong Debug build, gọi `DbgPrint`; cần ngoặc đôi |
| `CreateService` / `StartService` / `ControlService` | hàm (API) | Cài driver như service / nạp (`sc start`) / dỡ với `SERVICE_CONTROL_STOP` (`sc stop`) |
| `RtlGetVersion` | hàm | Lấy major/minor/build của Windows (bài tập cuối chương) |

## Code / mẫu thiết kế đáng nhớ

Driver hoàn chỉnh tối giản — mẫu khởi đầu cho mọi driver trong sách:

```cpp
#include <ntddk.h>

void SampleUnload(_In_ PDRIVER_OBJECT DriverObject) {
    UNREFERENCED_PARAMETER(DriverObject);
    KdPrint(("Sample driver Unload called\n"));
}

extern "C" NTSTATUS
DriverEntry(PDRIVER_OBJECT DriverObject, PUNICODE_STRING RegistryPath) {
    UNREFERENCED_PARAMETER(RegistryPath);
    DriverObject->DriverUnload = SampleUnload;
    KdPrint(("Sample driver initialized successfully\n"));
    return STATUS_SUCCESS;
}
```

Cài đặt, nạp, gỡ driver bằng sc.exe (chú ý khoảng trắng quanh dấu bằng) và bật test signing:

```text
sc create sample type= kernel binPath= c:\dev\sample\x64\debug\sample.sys
sc start sample
sc stop sample
bcdedit /set testsigning on
```

## Cạm bẫy & lưu ý

- Treat warnings as errors là mặc định — đừng tắt; thiếu `extern "C"` cho `DriverEntry` gây linker error khi build C++.
- Không hoàn tác tài nguyên của `DriverEntry` trong Unload → leak tồn tại đến lần reboot kế tiếp.
- Driver 64-bit phải được ký; test signing cần reboot và bị Secure Boot chặn trên Windows 10+ (local kernel debugging cũng vậy).
- `KdPrint` bắt buộc ngoặc đôi; `DbgPrint` cần registry `Debug Print Filter` (`DEFAULT` = 8) cộng restart, còn Enable Verbose Kernel Output của DebugView không đáng tin trên Windows 11.
- SDK/WDK phải cùng phiên bản; target cũ hơn Windows 10 phải đặt Target OS version trong project properties.

## Tóm lại cần nhớ

- Bộ công cụ chuẩn: Visual Studio 2019 (workload C++) + Windows 11 SDK (Debugging Tools) + Windows 11 WDK (template VS, build cho Windows 7 trở lên) + Sysinternals.
- Driver tối giản chỉ cần `DriverEntry` (`extern "C"`, trả `STATUS_SUCCESS`, gán `DriverUnload`) và Unload routine hoàn tác những gì `DriverEntry` đã làm.
- Vòng lặp develop: build trong Visual Studio, rồi `sc create` / `sc start` / `sc stop` bằng sc.exe với đặc quyền administrator.
- Trace bằng `KdPrint` (chỉ Debug build) và xem qua DebugView với Capture Kernel sau khi thiết lập registry `Debug Print Filter`.
- Chương sau trình bày các building block nền tảng của kernel API: khái niệm và cấu trúc dữ liệu cơ bản.
