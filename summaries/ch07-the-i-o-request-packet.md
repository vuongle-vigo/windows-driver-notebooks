# Chương 7: The I/O Request Packet

> Nguồn: *Windows Kernel Programming, 2nd Edition* — Pavel Yosifovich, trang 190–229

## Tổng quan

Chương giải thích cách yêu cầu I/O được đóng gói trong cấu trúc IRP và cách driver nhận, xử lý, hoàn tất chúng — công việc chính của driver sau `DriverEntry`. Cơ chế cốt lõi: IRP luôn đi kèm một/nhiều `IO_STACK_LOCATION` (mỗi layer trong device stack một cái), driver nhận qua dispatch routine theo major function code, và truy cập buffer client an toàn nhờ Buffered/Direct/Neither I/O cùng bốn METHOD_* cho IOCTL. Driver mẫu **Zero** (read trả buffer toàn 0, write "nuốt" buffer) tổng hợp toàn bộ.

## Nội dung theo từng mục

### Introduction to IRPs
- IRP cấp từ non-paged pool, thường bởi các manager trong Executive (I/O Manager, P&P Manager, Power Manager) nhưng driver cũng có thể tự cấp; ai cấp thì người đó giải phóng.
- IRP không bao giờ đứng một mình: khi cấp phải chỉ định số `IO_STACK_LOCATION` đi kèm, bằng số device object trong device stack, nằm liền sau IRP trong memory; driver lấy stack location của mình bằng macro `IoGetCurrentIrpStackLocation`.
- Tham số của request được "chia" giữa thân IRP và `IO_STACK_LOCATION` hiện tại.

### Device Nodes
- Windows I/O là device-centric: device object đặt tên được, client mở handle qua symbolic link bằng `CreateFile` (không nhận tên driver); device layering cho phép xếp lớp, request dành cho device dưới vẫn tới device trên cùng trước.
- Devnode phần cứng gồm: **PDO** do bus driver tạo (ví dụ pci.sys — chẳng có gì "physical", chỉ xác nhận có thiết bị trên slot, đọc được Vendor ID/Device ID), **FDO** do driver thật của hãng tạo, **FiDO** là filter tùy chọn.
- Trình tự P&P: bus driver tạo PDO → báo P&P manager → P&P lấy danh sách PDO và hardware ID → tra `HKLM\System\CurrentControlSet\Enum\PCI\(HardwareID)` → driver nạp, tạo FDO bằng `IoCreateDevice` rồi `IoAttachDeviceToDeviceStack` gắn lên trên; giá trị `Service` trỏ tới `Services` key nơi mọi driver đăng ký.
- Filter đăng ký qua giá trị multi-string `LowerFilters`/`UpperFilters` tại hardware ID key hoặc class key (`Control\Classes`); lower nạp từ dưới lên trước FDO, upper nạp sau; devnode hoạt động chuẩn có tối thiểu hai layer (PDO + FDO).

### IRP Flow
- Manager chỉ khởi tạo thân IRP và stack location đầu tiên rồi đưa cho layer trên cùng; driver nhận qua index trong mảng `MajorFunction` (ví dụ IRP_MJ_READ).
- Năm lựa chọn: pass down (`IoSkipCurrentIrpStackLocation` + `IoCallDriver`); tự xử lý rồi `IoCompleteRequest` (layer dưới không thấy); kết hợp xem/log/sửa rồi pass down; pass down kèm completion routine (`IoSetCompletionRoutine`); bất đồng bộ — `IoMarkIrpPending`, trả `STATUS_PENDING`, sau đó vẫn phải complete.
- `IoSkipCurrentIrpStackLocation` là tối ưu hóa so với `IoCopyIrpStackLocationToNext`: giảm con trỏ stack location đi 1, `IoCallDriver` tăng lại, nên layer dưới thấy đúng cùng stack location mà không cần copy.
- Khi có layer gọi `IoCompleteRequest`, IRP "nổi" ngược về originator; completion routines chạy theo thứ tự ngược đăng ký. Software driver trong sách thường là device duy nhất trong devnode nên chỉ xử lý rồi complete.

### IRP and I/O Stack Location
- IRP: `IoStatus` (`Status` + `Information` đa hình kiểu `ULONG_PTR` — với Read/Write là số byte truyền); `UserBuffer` (con trỏ buffer user thô; với DeviceIoControl là output buffer); `UserEvent` (`KEVENT` cho I/O async qua `OVERLAPPED`); `AssociatedIrp` (union: `SystemBuffer` cho Buffered I/O; `MasterIrp`/`IrpCount` cho cơ chế master/associated IRP hiếm dùng); `CancelRoutine` (hủy qua `CancelIo`/`CancelIoEx`); `MdlAddress` (MDL, dùng cho Direct I/O).
- `IO_STACK_LOCATION`: `MajorFunction` (hữu ích khi nhiều major code chung một routine); `MinorFunction` (chỉ `IRP_MJ_PNP`, `IRP_MJ_POWER`, `IRP_MJ_SYSTEM_CONTROL`/WMI có, xử lý bằng switch); `FileObject`, `DeviceObject`; `CompletionRoutine` + `Context` (đặt cho layer trên); union `Parameters` chứa phần lớn tham số — driver phải tự truy cập đúng struct (ví dụ `Parameters.Read`).

### Viewing IRP Information
- `!irpfind` quét non-paged pool để tìm IRP, không đối số thì liệt kê tất cả, có thể lọc theo tiêu chí.
- `!irp <addr>` liệt kê từng stack location (stack location hiện tại đánh dấu `>`): major/minor function, flags, DeviceObject, FileObject, completion routine, trạng thái Success/Error/Cancel/pending, và dòng Args (`Parameters.Others.Argument1`–4; với IOCTL là control code dạng link gọi `!ioctldecode`).
- Tham số details: 0 (mặc định, tóm tắt), 1 (chi tiết), 4 (thông tin Driver Verifier); `dt nt!_IRP` xem toàn bộ cấu trúc.

### Dispatch Routines
- Dispatch routine gắn với major code qua mảng `MajorFunction` của `DRIVER_OBJECT`; mọi routine cùng prototype `DRIVER_DISPATCH(PDEVICE_OBJECT DeviceObject, PIRP Irp)`.
- Thường chạy trong context thread yêu cầu ở `PASSIVE_LEVEL` (0), nhưng filter phía trên có thể gửi xuống bằng thread khác thậm chí `DISPATCH_LEVEL` (2) — driver vững vàng phải sẵn sàng.
- Việc đầu tiên là kiểm tra lỗi (độ dài buffer, control code có nhận diện được không); lỗi thì complete ngay với status phù hợp.
- Major function chính cho software driver: `IRP_MJ_CREATE` (`CreateFile`/`ZwCreateFile` — gần như bắt buộc, không có thì client không mở được handle); `IRP_MJ_CLOSE` (`CloseHandle`/`ZwClose` — chỗ undo những gì CREATE làm); `IRP_MJ_READ`/`IRP_MJ_WRITE` (`ReadFile`/`WriteFile` hoặc `ZwReadFile`/`ZwWriteFile`); `IRP_MJ_DEVICE_CONTROL` (`DeviceIoControl`/`ZwDeviceIoControlFile`); `IRP_MJ_INTERNAL_DEVICE_CONTROL` (chỉ kernel caller).

### Completing a Request
- Driver quyết định xử lý IRP thì bắt buộc phải complete, nếu không thread yêu cầu không kết thúc được → process treo thành "zombie process".
- Cách complete: đặt `Irp->IoStatus.Status` và `Information` rồi `IoCompleteRequest(Irp, IO_NO_INCREMENT)`; dispatch routine phải return đúng status đã ghi vào IRP; `Information` = 0 khi lỗi, ý nghĩa khi thành công tùy loại IRP.
- Đối số 2 là mức priority boost tạm cho thread gốc: priority tăng rồi giảm 1 mỗi quantum đến mức cũ; trần boost là 15, thread vốn trên 15 thì vô hiệu; software driver thường dùng `IO_NO_INCREMENT` (= 0) vì thread thực thi chính là thread gọi.

### Accessing User Buffers
- Context thuận lợi (IRQL 0 + đúng thread yêu cầu) thì buffer user truy cập đơn giản; nhưng thread khác trong process client có thể free buffer trước — handled bằng `__try`/`__except` (chương 6).
- Hai vấn đề khi context bất lợi: IRQL ≥ 2 (ví dụ DPC) thì không thể page fault; thread gọi là thread lạ thì pointer vô nghĩa vì truy cập nhầm address space — `__try`/`__except` khi đó hoặc vô dụng hoặc tệ hơn (đọc trúng memory ngẫu nhiên).
- I/O Manager cung cấp hai sơ chế gỡ cả hai vấn đề: Buffered I/O và Direct I/O; riêng cấu trúc non-paged trong system space (device object, IRP) luôn an toàn.

### Buffered I/O
- Bật bằng `DeviceObject->Flags |= DO_BUFFERED_IO;` (chỉ ảnh hưởng Read/Write).
- Các bước: I/O Manager cấp system buffer non-paged cùng size buffer user (`Parameters.Read.Length`/`Parameters.Write.Length`) vào `AssociatedIrp->SystemBuffer`; với write, copy user → system trước; dispatch routine khi đó dùng system buffer trực tiếp — system space hợp lệ từ mọi process context, non-paged nên mọi IRQL; khi complete, I/O Manager copy ngược `Information` byte về user buffer (cho read) rồi free system buffer.
- Copy-back làm bằng kernel APC đặc biệt queue vào thread yêu cầu: APC chạy đầu tiên khi thread được schedule, trong đúng process context, IRQL 1.
- Đặc điểm: dễ dùng; nhưng luôn có một lần copy → chỉ hợp buffer nhỏ (thường tối đa một page), buffer lớn nên dùng Direct I/O.

### Direct I/O
- Bật bằng `DeviceObject->Flags |= DO_DIRECT_IO;` — truy cập mọi IRQL, mọi thread, không copy.
- Các bước: I/O Manager fault các page của buffer vào RAM rồi lock (`MmProbeAndLockPages`) nên không thể page out; dựng MDL — cấu trúc mô tả buffer trong physical memory — lưu vào `Irp->MdlAddress`; driver khi cần gọi `MmGetSystemAddressForMdlSafe` để map thêm buffer sang system address (double mapping); khi complete, I/O Manager gỡ mapping, free MDL, unlock buffer.
- MDL thực chất là danh sách các MDL, mỗi cái mô tả một đoạn physically contiguous (buffer contiguous về virtual chưa chắc contiguous về physical — chi tiết chỉ quan trọng với DMA của hardware driver).
- `MmGetSystemAddressForMdlSafe(PVOID Mdl, ULONG Priority)` triển khai inline trong wdm.h: trả sẵn `MappedSystemVa` nếu MDL có cờ `MDL_MAPPED_TO_SYSTEM_VA`/`MDL_SOURCE_IS_NONPAGED_POOL`, ngược lại gọi `MmMapLockedPagesSpecifyCache`; Priority thường là `NormalPagePriority`; có thể gọi nhiều lần. Trả `NULL` khi hết system page tables — phải check và complete với `STATUS_INSUFFICIENT_RESOURCES`. Bản `MmGetSystemAddressForMdl` (không Safe) crash khi thất bại — không dùng. I/O Manager không map sẵn vì là tối ưu hóa: request lỗi thì driver khỏi cần map.
- Không set flag nào → ngầm dùng **Neither I/O**: không nhận trợ giúp gì, tự lo buffer user.

### User Buffers for IRP_MJ_DEVICE_CONTROL
- Với `IRP_MJ_DEVICE_CONTROL` (và `IRP_MJ_INTERNAL_DEVICE_CONTROL`), phương thức buffer chọn theo từng control code; `DeviceIoControl` nhận một control code và hai buffer tùy chọn input/output.
- Control code dựng bằng `CTL_CODE(DeviceType, Function, Method, Access)` = `((DeviceType) << 16) | ((Access) << 14) | ((Function) << 2) | (Method)`; DeviceType dùng hằng Microsoft (`FILE_DEVICE_DISK`...) hoặc custom tối thiểu 0x8000; Function là số thứ tự phân biệt, custom nên từ 0x800.
- Bốn phương thức (Table 7-1): `METHOD_NEITHER` — input/output đều Neither (input ở `Parameters.DeviceIoControl.Type3InputBuffer`, output ở `Irp->UserBuffer`; I/O Manager không check gì, hợp khi control code không cần buffer); `METHOD_BUFFERED` — cả hai Buffered (system buffer size = max(in, out), input copy vào `AssociatedIrp.SystemBuffer`, khi complete copy `Information` byte ra output); `METHOD_IN_DIRECT` và `METHOD_OUT_DIRECT` — đều input Buffered + output Direct, chỉ khác IN cho phép đọc còn OUT cho phép ghi output buffer.
- `Access`: `FILE_WRITE_ACCESS` (client → driver), `FILE_READ_ACCESS` (ngược lại), `FILE_ANY_ACCESS` (hai chiều) — sách khuyên luôn dùng `FILE_ANY_ACCESS` để sau khi deployed vẫn đổi cách dùng buffer mà không phá client cũ.

### Putting it All Together: The Zero Driver
- Zero: read zero out buffer, write chỉ tiêu thụ buffer như null device kinh điển.
- Chọn Direct I/O để tránh chi phí copy vì buffer client có thể rất lớn; project tạo từ "Empty WDM Project" trong Visual Studio, xóa file INF.

### Using a Precompiled Header
- Precompiled header tăng tốc biên dịch: gom `#include` ít đổi vào pch.h (`#pragma once` + `#include <ntddk.h>`), tạo pch.cpp chỉ chứa `#include "pch.h"`; đặt Precompiled Header = Use/pch.h cho project (chọn All Configurations/All Platforms) và = Create cho pch.cpp.
- Từ đó mọi file C/CPP phải `#include "pch.h"` đầu tiên — bất kỳ gì đứng trước dòng này không được biên dịch.

### The DriverEntry Routine
- Gán `DriverObject->DriverUnload = ZeroUnload`; `MajorFunction[IRP_MJ_CREATE]` và `[IRP_MJ_CLOSE]` cùng trỏ `ZeroCreateClose`, `IRP_MJ_READ` → `ZeroRead`, `IRP_MJ_WRITE` → `ZeroWrite`.
- Tạo device `\Device\Zero` (`FILE_DEVICE_UNKNOWN`) và symbolic link `\??\Zero` bên trong khối `do { ... } while (false)` — không phải vòng lặp, chỉ là mẹo `break` khi lỗi; sau khối check status và undo (chỉ `IoDeleteDevice`) một chỗ duy nhất, dễ mở rộng hơn cả dùng `goto` (tác giả né vì "goto considered harmful").
- Trước khi tạo symbolic link, đặt `DeviceObject->Flags |= DO_DIRECT_IO;` để chọn Direct I/O.

### The Create and Close Dispatch Routines
- Helper `CompleteIrp(PIRP Irp, NTSTATUS status = STATUS_SUCCESS, ULONG_PTR info = 0)` gán `IoStatus`, gọi `IoCompleteRequest(Irp, IO_NO_INCREMENT)`, trả status.
- Nhờ default arguments của helper, `ZeroCreateClose` chỉ còn `return CompleteIrp(Irp);` — Create/Close hoàn tất thành công ngay.

### The Read Dispatch Routine
- `ZeroRead` lấy `len = stack->Parameters.Read.Length`; nếu `len == 0` complete với `STATUS_INVALID_BUFFER_SIZE`.
- Vì Direct I/O: `NT_ASSERT(Irp->MdlAddress)` rồi `MmGetSystemAddressForMdlSafe(Irp->MdlAddress, NormalPagePriority)`; `NULL` → `STATUS_INSUFFICIENT_RESOURCES`.
- `memset(buffer, 0, len)` (hoặc macro `RtlZeroMemory`) rồi `CompleteIrp(Irp, STATUS_SUCCESS, len)` — `Information` phải bằng độ dài buffer để client biết số byte truyền (tham số áp chót của `ReadFile`).

### The Write Dispatch Routine
- `ZeroWrite` chỉ `CompleteIrp(Irp, STATUS_SUCCESS, stack->Parameters.Write.Length)` — "nuốt" buffer, không gọi `MmGetSystemAddressForMdlSafe` vì không cần chạm buffer.
- Đây cũng là lý do I/O Manager không map sẵn: chuẩn bị MDL xong, để driver tự quyết có map hay không.

### Test Application
- Client `CreateFile(L"\\\\.\\Zero", GENERIC_READ | GENERIC_WRITE, ...)` rồi đọc 64 byte vào buffer đã điền dữ liệu khác 0, kiểm tra toàn bộ là 0 và số byte đọc đúng.
- Tiếp theo ghi 1024 byte rác, kiểm tra số byte ghi trả về đúng; cuối cùng `CloseHandle`.

### Read/Write Statistics
- Thêm biến toàn cục `long long g_TotalRead; long long g_TotalWritten;` (global tự khởi tạo 0) và file chung driver/client `ZeroCommon.h` chứa control code + struct dùng chung.
- `IOCTL_ZERO_GET_STATS` = `CTL_CODE(DEVICE_ZERO /*0x8022*/, 0x800, METHOD_BUFFERED, FILE_ANY_ACCESS)` — METHOD_BUFFERED vì dữ liệu nhỏ (2 × 8 byte); `IOCTL_ZERO_CLEAR_STATS` = `CTL_CODE(DEVICE_ZERO, 0x801, METHOD_NEITHER, FILE_ANY_ACCESS)` — không cần buffer; struct chung: `struct ZeroStats { long long TotalRead; long long TotalWritten; };`.
- `ZeroDeviceControl` lấy `irpSp->Parameters.DeviceIoControl`, status mặc định `STATUS_INVALID_DEVICE_REQUEST`, `len = 0`; switch theo `dic.IoControlCode`: GET_STATS kiểm tra `OutputBufferLength < sizeof(ZeroStats)` → `STATUS_BUFFER_TOO_SMALL`, lấy `stats = (ZeroStats*)Irp->AssociatedIrp.SystemBuffer` (NULL → `STATUS_INVALID_PARAMETER`), điền số liệu, `len = sizeof(ZeroStats)`; CLEAR_STATS gán `g_TotalRead = g_TotalWritten = 0`; cuối cùng `return CompleteIrp(Irp, status, len);`.
- Cập nhật stats thread-safe bằng `InterlockedAdd64(&g_TotalWritten, len)` trong `ZeroWrite` (ZeroRead tương tự). Đọc stats không bảo vệ vẫn technically là data race (torn reads) — có thể dùng mutex/fast mutex hoặc `ReadAcquire64` (x86/x64 là read thường vì CPU tự chống torn read; ARM cần memory barrier).
- Bài tập gợi ý: lưu stats vào Registry trước khi unload, đọc lại khi load; thay Interlocked bằng fast mutex.

## API / cấu trúc / hằng số quan trọng

| Tên | Loại | Vai trò & ghi chú ngắn |
|---|---|---|
| `IRP` | struct | Gói yêu cầu I/O (non-paged pool); chứa `IoStatus`, `UserBuffer`, `AssociatedIrp.SystemBuffer`, `MdlAddress`... |
| `IO_STACK_LOCATION` | struct | Tham số theo từng layer: `MajorFunction`, `MinorFunction`, union `Parameters` |
| `IoGetCurrentIrpStackLocation` | macro | Lấy stack location hiện tại |
| `IoCreateDevice` / `IoCreateSymbolicLink` | hàm | Tạo device object / symbolic link cho client mở |
| `IoAttachDeviceToDeviceStack` | hàm | Gắn FDO/filter lên layer dưới trong device stack |
| `IoCallDriver` | hàm | Chuyển IRP xuống device thấp hơn |
| `IoSkipCurrentIrpStackLocation` | macro | Pass down không đổi stack location (rẻ hơn copy) |
| `IoSetCompletionRoutine` / `IoMarkIrpPending` | macro | Đặt completion routine / đánh dấu IRP pending (`STATUS_PENDING`) |
| `IoCompleteRequest` | hàm | Hoàn tất IRP; đối số 2 là priority boost (`IO_NO_INCREMENT` = 0) |
| `DO_BUFFERED_IO` / `DO_DIRECT_IO` | hằng số (flag) | Chọn Buffered/Direct I/O cho Read/Write trên device object |
| `METHOD_BUFFERED` / `METHOD_NEITHER` / `METHOD_IN_DIRECT` / `METHOD_OUT_DIRECT` | hằng số | Chọn buffer method từng IOCTL trong `CTL_CODE` (Table 7-1) |
| `CTL_CODE` | macro | Dựng control code; DeviceType custom ≥ 0x8000, Function custom từ 0x800 |
| `FILE_ANY_ACCESS` / `FILE_READ_ACCESS` / `FILE_WRITE_ACCESS` | hằng số | Thành phần Access; sách khuyên luôn dùng FILE_ANY_ACCESS |
| `MmGetSystemAddressForMdlSafe` | hàm (inline) | Map MDL sang system address; NULL khi thiếu resource |
| `MmMapLockedPagesSpecifyCache` | hàm | Hàm generic mà MmGetSystemAddressForMdlSafe gọi |
| `MmProbeAndLockPages` / `MmUnlockPages` | hàm | Lock/unlock buffer trong RAM; dùng được ngoài Direct I/O |
| `MmGetSystemAddressForMdl` | hàm | Bản không Safe — thất bại thì crash, không dùng |
| `InterlockedAdd64` / `ReadAcquire64` | hàm | Cộng/đọc 64-bit an toàn giữa các thread (stats) |
| `!irpfind` / `!irp` | debugger command | Tìm IRP trong pool / xem chi tiết một IRP (details 0/1/4) |
| `DRIVER_DISPATCH` | typedef | Prototype chung của mọi dispatch routine |

## Code / mẫu thiết kế đáng nhớ

Hoàn tất IRP trong dispatch routine — quy chuẩn mọi software driver (kèm helper `CompleteIrp` của Zero):

```c
Irp->IoStatus.Status = STATUS_XXX;
Irp->IoStatus.Information = bytes;   // 0 nếu lỗi; số byte với Read/Write
IoCompleteRequest(Irp, IO_NO_INCREMENT);
return STATUS_XXX;                   // phải là status vừa ghi vào IRP
```

Chọn buffer access method trên device object (áp cho Read/Write):

```c
DeviceObject->Flags |= DO_BUFFERED_IO; // Buffered: copy qua system buffer, buffer nhỏ
DeviceObject->Flags |= DO_DIRECT_IO;   // Direct: MDL + map, không copy, buffer lớn
```

`ZeroRead` — quy trình chuẩn xử lý Read với Direct I/O:

```c
auto stack = IoGetCurrentIrpStackLocation(Irp);
auto len = stack->Parameters.Read.Length;
if (len == 0) return CompleteIrp(Irp, STATUS_INVALID_BUFFER_SIZE);
NT_ASSERT(Irp->MdlAddress);
auto buffer = MmGetSystemAddressForMdlSafe(Irp->MdlAddress, NormalPagePriority);
if (!buffer) return CompleteIrp(Irp, STATUS_INSUFFICIENT_RESOURCES);
memset(buffer, 0, len);
return CompleteIrp(Irp, STATUS_SUCCESS, len);
```

## Cạm bẫy & lưu ý

- Cấm viết `return Irp->IoStatus.Status;` sau khi đã `IoCompleteRequest`: IRP có thể đã bị free, thậm chí cấp phát lại cho IRP khác — crash hoặc trả status ngẫu nhiên.
- Quên complete IRP → thread yêu cầu không kết thúc được → "zombie process".
- Dispatch routine có thể bị filter gửi xuống bằng thread bất kỳ ở IRQL cao hơn (`DISPATCH_LEVEL`); khi đó buffer thô (Neither) vô nghĩa hoặc gây access violation, `__try`/`__except` không cứu được việc đọc memory của process khác.
- `MmGetSystemAddressForMdlSafe` trả `NULL` khi hệ thống hết system page tables — bắt buộc check, trả `STATUS_INSUFFICIENT_RESOURCES`; dùng nhầm `MmGetSystemAddressForMdl` thì crash.
- Buffered I/O luôn tốn một lần copy — chỉ cho buffer nhỏ (≈ một page); buffer lớn dùng Direct I/O.
- `METHOD_NEITHER`: I/O Manager không kiểm tra pointer input/output; dùng khi control code không cần buffer hoặc tự xử lý cẩn thận.
- `#include "pch.h"` phải đứng đầu mọi file nguồn; nội dung đứng trước nó không được biên dịch.
- Priority boost trần là 15; thread vốn trên 15 thì boost vô hiệu. Đọc stats toàn cục không bảo vệ là data race (torn reads) — dùng Interlocked/mutex/fast mutex.

## Tóm lại cần nhớ

- IRP + `IO_STACK_LOCATION` là xương sống xử lý request: driver nhận qua mảng `MajorFunction`, lấy stack location bằng `IoGetCurrentIrpStackLocation`; tham số nằm trong union `Parameters`.
- Năm cách ứng phó IRP: pass down, tự xử lý, kết hợp, pass down kèm completion routine, bất đồng bộ (`IoMarkIrpPending` + `STATUS_PENDING`); complete bằng `IoCompleteRequest` và return đúng status đã ghi.
- Truy cập buffer user an toàn mọi context: Buffered I/O (copy, buffer nhỏ), Direct I/O (MDL + `MmGetSystemAddressForMdlSafe`, buffer lớn), Neither (tự lo); với IOCTL, method chọn theo control code qua `CTL_CODE` với 4 giá trị METHOD_*.
- Driver mẫu Zero tổng hợp cả chương: Direct I/O, helper `CompleteIrp`, mẫu xử lý lỗi `do/while(false)` trong `DriverEntry`, IOCTL thống kê với `InterlockedAdd64`.
- Debugger hỗ trợ IRP: `!irpfind` tìm, `!irp` xem chi tiết stack locations; nền tảng này dẫn tới process/thread callbacks ở chương 9.
