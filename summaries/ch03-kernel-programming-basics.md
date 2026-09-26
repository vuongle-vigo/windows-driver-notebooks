# Chương 3: Kernel Programming Basics

> Nguồn: *Windows Kernel Programming, 2nd Edition* — Pavel Yosifovich, trang 39–61

## Tổng quan

Chương đặt nền móng trước khi viết driver hoàn chỉnh đầu tiên: khác biệt giữa lập trình user-mode và kernel-mode, build Debug/Release, tổ chức Kernel API, quy ước `NTSTATUS`, chuỗi `UNICODE_STRING`, cấp phát bộ nhớ từ pool, danh sách liên kết `LIST_ENTRY`, và các cấu trúc trung tâm `DRIVER_OBJECT`, `OBJECT_ATTRIBUTES`, `DEVICE_OBJECT`. Thông điệp xuyên suốt: lỗi kernel làm crash cả hệ thống, nên code phải cẩn trọng và không bao giờ bỏ qua kiểm tra lỗi.

## Nội dung theo từng mục

### General Kernel Programming Guidelines

Lập trình driver cần WDK; Kernel API là các hàm C giống user-mode nhưng hậu quả lỗi nặng hơn nhiều (Bảng 3-1).

- **Unhandled Exceptions**: exception không bắt trong kernel gây BSOD — đây thực chất là cơ chế bảo vệ, tránh hỏng hóc không phục hồi (xóa file, hỏng registry) nếu để code chạy tiếp.
- **Termination**: process kết thúc là kernel tự giải phóng mọi bộ nhớ/handle; driver unload còn giữ tài nguyên thì leak cho tới lần boot sau. Kernel không dọn giúp vì không biết leak có chủ ý không (vd: driver cấp buffer đưa cho driver khác dùng tiếp) — driver phải tự dọn dẹp.
- **Function Return Values**: luôn kiểm tra status trả về từ kernel API, kể cả hàm có vẻ "vô hại".
- **IRQL**: user-mode luôn ở mức 0; kernel code có thể chạy ở `DISPATCH_LEVEL` (2) trở lên, nơi chỉ được dùng API cho phép (chi tiết chương 6).
- **C++ Usage**: hỗ trợ chính thức từ VS2012/WDK 8, nhưng kernel không có C++ runtime nên: `new`/`delete` không biên dịch được (có thể overload để gọi hàm cấp phát kernel); global object có constructor không mặc định không được gọi (workaround: hàm `Init` gọi từ `DriverEntry`, hoặc cấp phát object động); không `try`/`catch`/`throw` (chỉ SEH); không standard library (template như tính năng ngôn ngữ vẫn OK). Sách dùng nhiều `nullptr`, `auto`, template, overload `new`/`delete`, constructor/destructor cho idiom RAII chống leak. Chuẩn C++ nào cũng được (mặc định C++14, một số phần cần C++17); viết thuần C vẫn ổn.
- **Testing and Debugging**: phải test/debug trên máy thứ hai (thường là VM) vì breakpoint trong kernel đóng băng cả máy; host chạy debugger, target chạy driver, nối qua kênh riêng (chương 5).

### Debug vs. Release Builds

- Kernel gọi Debug là **Checked**, Release là **Free** (tài liệu cũ vẫn dùng).
- Kernel Debug build định nghĩa symbol `DBG` = 1 (thay cho `_DEBUG` ở user-mode); nhờ đó macro `KdPrint` biên dịch thành `DbgPrint` ở Debug nhưng thành "không gì cả" ở Release, vì các lời gọi này đắt tiền.

### The Kernel API

- Gồm các hàm export từ các thành phần kernel, đa số trong NtOskrnl.exe, một phần trong HAL. Prefix cho biết thành phần (Bảng 3-2): `Ex`, `Ke`, `Mm`, `Rtl`, `FsRtl`, `Flt`, `Ob`, `Io`, `Se`, `Ps`, `Po`, `Wmi`, `Zw`, `Hal`, `Cm` (registry). Nhiều hàm export không được tài liệu hóa.
- **Zw vs Nt**: user-mode gọi hàm Nt (vd `NtCreateFile`) sẽ bị Executive kiểm tra theo previous mode của caller — lưu trong member không tài liệu hóa `PreviousMode` của `KTHREAD`, query bằng `ExGetPreviousMode`. Hàm `Zw` đặt previous mode = `KernelMode` (0) rồi gọi hàm Nt tương ứng, bỏ qua một số kiểm tra security/buffer — driver nên gọi hàm `Zw` trừ khi có lý do chính đáng.

### Functions and Error Codes

- `NTSTATUS` là số nguyên có dấu 32-bit: `STATUS_SUCCESS` (0) = thành công, giá trị âm = lỗi; đầy đủ trong <ntstatus.h>; kiểm tra bằng macro `NT_SUCCESS` (test bit cao nhất).
- `NTSTATUS` bubble lên user-mode được ánh xạ (không 1-1) thành `ERROR_yyy` dương cho `GetLastError`.
- Hàm nội bộ của driver cũng nên trả `NTSTATUS` để propagate lỗi; giá trị "thật" trả ra qua tham số con trỏ/reference.

### Strings

- "Unicode" trong kernel ≈ UTF-16: 2 byte mỗi ký tự.
- `UNICODE_STRING` gồm `Length` (byte, không tính NULL terminator — terminator không bắt buộc), `MaximumLength`, `Buffer`.
- Thao tác qua hàm `Rtl` (Bảng 3-3): `RtlInitUnicodeString` (init từ C-string, **không cấp phát**), `RtlCopyUnicodeString` (destination phải cấp phát sẵn + set `MaximumLength`), `RtlCompareUnicodeString`/`RtlEqualUnicodeString` (chọn phân biệt hoa thường), `RtlAppendUnicodeStringToString`, `RtlAppendUnicodeToString`.
- Kernel còn có các hàm kiểu CRT: `wcscpy_s`, `wcscat_s`, `wcslen`, `wcschr`… (`wcs` = Unicode, `str` = ANSI, hậu tố `_s` = bản an toàn có giới hạn độ dài). Cấm dùng bản không an toàn; include <dontuse.h> để trình biên dịch báo lỗi nếu lỡ dùng.

### Dynamic Memory Allocation

- Stack kernel thread rất nhỏ nên dữ liệu lớn phải cấp phát động từ pool: **Paged pool** (có thể page out) và **Non-Paged pool** (luôn ở RAM). Non-paged nên dùng tiết kiệm; trong `POOL_TYPE`, driver chỉ nên dùng `PagedPool`, `NonPagedPool`, `NonPagedPoolNx`.
- Hàm chính (Bảng 3-4): `ExAllocatePoolWithTag` (tag 4 byte), `ExAllocatePoolZero` (inline trong wdm.h, thêm flag `POOL_ZERO_ALLOCATION` = 1024), `ExAllocatePoolWithQuotaTag` (tính quota process gọi), `ExFreePool` (tự biết pool nguồn). `ExAllocatePool` đã lỗi thời (tag `enoN`, trước là `` mdW).
- Tag nên gồm tối đa 4 ký tự ASCII in được, nếu không Driver Verifier sẽ phàn nàn; xem allocation theo tag bằng Poolmon/PoolMonXv2 để phát hiện leak.

### Linked Lists

- Kernel dùng circular doubly linked list khắp nơi: các `EPROCESS` nối nhau qua member `ActiveProcessLinks`, head là `PsActiveProcessHead`.
- `LIST_ENTRY` (`Flink`/`Blink`) được nhúng vào struct dữ liệu thật; từ con trỏ entry lấy struct chứa nó bằng macro `CONTAINING_RECORD` (tự tính offset và cast).
- Thao tác (Bảng 3-5) đều constant time: `InitializeListHead`, `InsertHeadList`, `InsertTailList`, `IsListEmpty`, `RemoveHeadList`, `RemoveTailList`, `RemoveEntryList`; biến thể `ExInterlockedInsertHeadList`/`InsertTailList`/`RemoveHeadList` làm atomic bằng spin lock.

### The Driver Object

- `DRIVER_OBJECT` là "semi-documented", do kernel cấp phát và init một phần rồi truyền cho `DriverEntry`; việc của driver là init tiếp để khai báo mình hỗ trợ thao tác nào.
- Dispatch Routines: mảng con trỏ hàm `MajorFunction`, chỉ số là các mã `IRP_MJ_` (Bảng 3-6): CREATE (0, do `CreateFile`/`ZwCreateFile`), CLOSE (2, do `CloseHandle`/`ZwClose`), READ (3), WRITE (4), DEVICE_CONTROL (14, do `DeviceIoControl`), INTERNAL_DEVICE_CONTROL (15, chỉ caller kernel-mode), SHUTDOWN (16, nếu đăng ký `IoRegisterShutdownNotification`), CLEANUP (18, handle cuối đóng nhưng file object còn reference), PNP (31), POWER (22).
- Mặc định mọi entry trỏ tới `IopInvalidDeviceRequest` (trả lỗi không hỗ trợ), nên driver chỉ ghi đè entry mình cần; tối thiểu phải hỗ trợ CREATE/CLOSE để client mở được handle tới device object — nếu không sẽ không giao tiếp được với driver.

### Object Attributes

- `OBJECT_ATTRIBUTES` xuất hiện trong nhiều kernel API; init bằng macro `InitializeObjectAttributes` (tự set `Length`), hoặc `RTL_CONSTANT_OBJECT_ATTRIBUTES` khi chỉ cần name + attributes.
- Member: `ObjectName` (`UNICODE_STRING`, có thể NULL — vd `ZwOpenProcess` mở theo PID vì process không có tên), `RootDirectory` (chỉ dùng cho tên tương đối), `Attributes` (flag `OBJ_`), `SecurityDescriptor` (NULL = default theo token caller), `SecurityQualityOfService` (hầu như không cần).
- Flag `OBJ_` (Bảng 3-7): `INHERIT` (2), `PERMANENT` (0x10, sống dù đóng hết handle), `EXCLUSIVE` (0x20), `CASE_INSENSITIVE` (0x40), `OPENIF` (0x80, mở nếu có chứ không tạo mới), `OPENLINK` (0x100, mở chính symbolic link), `KERNEL_HANDLE` (0x200, hợp lệ mọi process context, user-mode không dùng được), `FORCE_ACCESS_CHECK` (0x400), `IGNORE_IMPERSONATED_DEVICEMAP` (0x800), `DONT_REPARSE` (0x1000, trả `STATUS_REPARSE_POINT_ENCOUNTERED`).
- `CLIENT_ID` chứa `UniqueProcess`/`UniqueThread`: kiểu `HANDLE` nhưng thực chất là PID/TID, vì ID sinh từ private handle table — luôn bội của 4 và không trùng handle.
- Ví dụ sách: mở process bằng `ZwOpenProcess` (cast PID bằng `ULongToHandle`); mở file bằng `ZwOpenFile` — tên file nằm trong `OBJECT_ATTRIBUTES`, không có tham số riêng; cần `RtlInitUnicodeString` trước.

### Device Objects

- Client không nói chuyện với driver object mà với **device object** (`DEVICE_OBJECT`, semi-documented); driver phải tạo ít nhất một device object và đặt tên.
- Tham số "file name" của `CreateFile` thực chất trỏ tới tên device/symbolic link; mở handle tạo ra `FILE_OBJECT`. Symbolic link dùng được từ user-mode nằm trong thư mục Object Manager `??` (Global?? trong WinObj); các tên interface dài do `IoRegisterDeviceInterface` sinh ra cho driver hardware. Link trỏ tới tên nội bộ dưới `\Device`, user-mode không truy cập trực tiếp được — kernel caller dùng `IoGetDeviceObjectPointer`.
- Ví dụ Process Explorer: driver tạo device `\Device\PROCEXP152` kèm symlink `PROCEXP152`; client phải mở bằng prefix `\\.\` (vd `LR"(\\.\PROCEXP152)"` từ C++11) để parser không hiểu là file thường.
- `IoCreateDevice` tạo device object và lưu vào member `DeviceObject` của `DRIVER_OBJECT`; nhiều device nối singly linked list qua `NextDevice`, chèn vào đầu nên device tạo đầu tiên nằm cuối (`NextDevice` = NULL).

#### Opening Devices Directly

- Device không có symlink vẫn mở được bằng native API `NtOpenFile`/`NtCreateFile` (prototype trong <Winternl.h>, cần link ntdll); prototype giống hệt `ZwOpenFile` nhưng gọi từ user-mode; header cũ còn dùng macro `IN`/`OUT` chưa chuyển sang SAL.
- Ví dụ Beep: `Beep(freq, ms)` là hàm đồng bộ, thực chất gọi device `\Device\Beep` không có symlink. App mẫu: link ntdll bằng `#pragma comment(lib, "ntdll")`, `NtOpenFile` mở device (tên có sẵn trong `DD_BEEP_DEVICE_NAME_U` của <ntddbeep.h>), rồi `DeviceIoControl` với `IOCTL_BEEP_SET` + struct `BEEP_SET_PARAMETERS`; lệnh trả về ngay nên phải `Sleep(duration)` trước `CloseHandle`, nếu không âm thanh bị cắt.

## API / cấu trúc / hằng số quan trọng

| Tên | Loại | Vai trò & ghi chú ngắn |
|---|---|---|
| `NTSTATUS` / `NT_SUCCESS` | hằng số/macro | Trạng thái 32-bit; 0 = OK, âm = lỗi; `NT_SUCCESS` test bit cao nhất |
| `DBG` / `KdPrint` | hằng số/macro | Debug build =1; `KdPrint` → `DbgPrint` ở Debug, rỗng ở Release |
| `ExGetPreviousMode` | hàm | Lấy previous mode của caller |
| `Zw*` (vd `ZwCreateFile`) | hàm | Set previous mode = KernelMode rồi gọi hàm Nt, bỏ qua vài kiểm tra |
| `UNICODE_STRING` | struct | `Length`/`MaximumLength` (byte) + `Buffer`; UTF-16 |
| `RtlInitUnicodeString` | hàm | Init từ C-string, không cấp phát |
| `ExAllocatePoolWithTag` / `ExFreePool` | hàm | Cấp phát pool kèm tag ASCII / giải phóng |
| `POOL_TYPE` | hằng số | Chỉ nên dùng `PagedPool`, `NonPagedPool`, `NonPagedPoolNx` |
| `LIST_ENTRY` | struct | Node `Flink`/`Blink` nhúng trong struct dữ liệu |
| `CONTAINING_RECORD` | macro | Từ entry lấy con trỏ struct chứa nó |
| `InitializeListHead`, `InsertHeadList`, `InsertTailList`, `RemoveHeadList`, `RemoveTailList`, `RemoveEntryList`, `IsListEmpty` | hàm | Thao tác danh sách O(1); biến thể `ExInterlocked*` dùng spin lock |
| `DRIVER_OBJECT` | struct | Driver init `DriverUnload` + mảng `MajorFunction` trong `DriverEntry` |
| `IRP_MJ_*` | hằng số | Chỉ số dispatch routine; default là `IopInvalidDeviceRequest` |
| `OBJECT_ATTRIBUTES` | struct | Tên, root, flags, security; init bằng `InitializeObjectAttributes`/`RTL_CONSTANT_OBJECT_ATTRIBUTES` |
| Flag `OBJ_` (`KERNEL_HANDLE`, `CASE_INSENSITIVE`, `PERMANENT`, `OPENIF`, `DONT_REPARSE`…) | hằng số | Điều khiển hành vi mở/tạo object (Bảng 3-7) |
| `CLIENT_ID` | struct | `UniqueProcess`/`UniqueThread` = PID/TID, không phải handle |
| `ZwOpenProcess` / `ZwOpenFile` | hàm | Mở handle process/file từ kernel |
| `NtOpenFile` | hàm | Native API mở device trực tiếp từ user-mode (<Winternl.h>, link ntdll) |
| `IoCreateDevice` | hàm | Tạo device object, nối vào `DRIVER_OBJECT.DeviceObject` |
| `IoGetDeviceObjectPointer` | hàm | Kernel lấy device từ tên nội bộ `\Device\...` |
| `IOCTL_BEEP_SET` / `BEEP_SET_PARAMETERS` | hằng số/struct | Điều khiển thiết bị Beep (<ntddbeep.h>) |

## Code / mẫu thiết kế đáng nhớ

1. Lưu `RegistryPath` lúc `DriverEntry`, giải phóng lúc unload — mẫu "driver tự dọn dẹp" kèm tag riêng để truy vết leak:

```c
#define DRIVER_TAG 'dcba'
UNICODE_STRING g_RegistryPath;
extern "C" NTSTATUS
DriverEntry(PDRIVER_OBJECT DriverObject, PUNICODE_STRING RegistryPath) {
    DriverObject->DriverUnload = SampleUnload;
    g_RegistryPath.Buffer = (WCHAR*)ExAllocatePoolWithTag(PagedPool,
        RegistryPath->Length, DRIVER_TAG);
    if (g_RegistryPath.Buffer == nullptr)
        return STATUS_INSUFFICIENT_RESOURCES;
    g_RegistryPath.MaximumLength = RegistryPath->Length;
    RtlCopyUnicodeString(&g_RegistryPath, (PCUNICODE_STRING)RegistryPath);
    return STATUS_SUCCESS;  // SampleUnload: ExFreePool(g_RegistryPath.Buffer);
}
```

2. Mở process theo PID — kết hợp `CLIENT_ID` và `RTL_CONSTANT_OBJECT_ATTRIBUTES` với `OBJ_KERNEL_HANDLE`:

```c
CLIENT_ID cid;
cid.UniqueProcess = ULongToHandle(pid);  // PID, không phải handle
cid.UniqueThread = nullptr;
OBJECT_ATTRIBUTES procAttributes =
    RTL_CONSTANT_OBJECT_ATTRIBUTES(nullptr, OBJ_KERNEL_HANDLE);
return ZwOpenProcess(phProcess, accessMask, &procAttributes, &cid);
```

## Cạm bẫy & lưu ý

- Bỏ qua status trả về của kernel API có thể crash cả hệ thống; driver unload chưa dọn thì leak kéo dài tới lần boot sau — không ai dọn giúp.
- Giới hạn C++ kernel: không `new`/`delete` gốc, không global object có constructor phức tạp, không try/catch/throw, không STL — exception chỉ dùng SEH.
- `RtlInitUnicodeString` không cấp phát; `RtlCopyUnicodeString` đòi destination đã cấp phát và set `MaximumLength`. Cấm hàm chuỗi không an toàn.
- Ưu tiên PagedPool, non-paged chỉ khi cần; `ExAllocatePool` lỗi thời; tag phải ASCII in được (Driver Verifier kiểm tra); `KdPrint` im lặng ở Release.
- Ở IRQL ≥ 2 chỉ được gọi API cho phép; debug kernel phải qua máy/VM thứ hai vì breakpoint đóng băng cả máy.
- Mở device qua symlink phải prepend `\\.\`; device không có symlink thì mở thẳng bằng `NtOpenFile`.

## Tóm lại cần nhớ

- Kernel code được tin tưởng tuyệt đối nên phải kiểm tra mọi status và tự dọn tài nguyên; sơ suất dẫn tới BSOD hoặc leak tới reboot.
- Driver gọi system service nên dùng hàm `Zw`.
- Ba khối dữ liệu nền: `UNICODE_STRING`, pool allocation có tag, `LIST_ENTRY` + `CONTAINING_RECORD`.
- Client giao tiếp qua device object (không phải driver object): cần tên nội bộ + symbolic link (`\\.\Name`), hoặc mở thẳng bằng `NtOpenFile`.
- Khả năng driver khai báo qua mảng `MajorFunction`; mặc định mọi request bị từ chối, tối thiểu cần CREATE/CLOSE.
- Summary của sách: chương cung cấp cấu trúc dữ liệu, khái niệm và API nền tảng; chương 4 sẽ dựng driver hoàn chỉnh cùng client application.
