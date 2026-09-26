# Chương 4: Driver from Start to Finish

> Nguồn: *Windows Kernel Programming, 2nd Edition* — Pavel Yosifovich, trang 62–80

## Tổng quan

Chương xây dựng một software driver hoàn chỉnh tên `Booster` kèm client user-mode: client gửi thread ID và priority, driver gọi `KeSetPriorityThread` đặt priority bất kỳ trong khoảng 1–31 cho thread bất kỳ — điều Windows API user-mode không cho phép. Chương đi trọn luồng chuẩn của driver: khởi tạo trong `DriverEntry` (Unload, dispatch routines, device object, symbolic link), giao tiếp qua `WriteFile`, xử lý `IRP_MJ_CREATE`/`IRP_MJ_CLOSE`/`IRP_MJ_WRITE`, cài đặt và kiểm thử.

## Nội dung theo từng mục

### Introduction
- Vấn đề: user mode chỉ đặt priority qua process priority class (`SetPriorityClass`, 6 class) cộng offset từng thread (`SetThreadPriority`, offset −2..+2, và 2 mức saturation `THREAD_PRIORITY_IDLE`, `THREAD_PRIORITY_TIME_CRITICAL`).
- Bảng 4-1: class High chỉ có 6 mức (không phải 7); riêng Real-time chọn được mọi mức 16–31. Real-time không biến Windows thành real-time OS và cần quyền administrator, nếu không bị hạ xuống High.
- Mục tiêu driver: đặt priority thành bất kỳ số nào, bất kể priority class của process.

### Driver Initialization
- Tạo "WDM Empty Project" tên Booster, xóa INF, thêm `Booster.cpp` với `#include <ntddk.h>`; `DriverEntry` ban đầu chỉ trả `STATUS_SUCCESS`.
- `DriverEntry` của software driver cần 4 việc: đặt Unload routine (`DriverObject->DriverUnload`), đặt dispatch routines, tạo device object, tạo symbolic link.
- `IRP_MJ_CREATE` và `IRP_MJ_CLOSE` gần như bắt buộc (nếu không không thể mở handle); cả hai trỏ vào cùng `BoosterCreateClose` vì chỉ cần "approve" request. Mọi major function dùng chung prototype: `NTSTATUS f(PDEVICE_OBJECT, PIRP)`.

### Passing Information to the Driver
- Client có 3 lựa chọn: `WriteFile`, `ReadFile`, `DeviceIoControl`; Read không hợp lý vì dữ liệu đi vào driver. Kinh nghiệm chung: dùng Write nếu đúng nghĩa ghi, còn lại ưu tiên `DeviceIoControl`.
- Sách chọn `WriteFile` vì đơn giản hơn: gán `BoosterWrite` vào `MajorFunction[IRP_MJ_WRITE]`.

### Client / Driver Communication Protocol
- Giao thức buffer khai báo trong header chung `BoosterCommon.h` (dùng bởi cả driver và client): `struct ThreadData { ULONG ThreadId; int Priority; };`.
- Chọn `ULONG` vì có ở cả kernel và user mode (`DWORD` chỉ có trong header user mode). Thread ID là số 32-bit unsigned; priority hợp lệ trong 1..31.

### Creating the Device Object
- `IoCreateDevice`: `DriverObject`; `DeviceExtensionSize` = 0 với software driver một thiết bị (state dùng biến global); `DeviceName` trong thư mục `\Device`; `DeviceType` = `FILE_DEVICE_UNKNOWN`; `DeviceCharacteristics` = 0 (hoặc `FILE_DEVICE_SECURE_OPEN` nếu có namespace thật); `Exclusive` = `FALSE` (`TRUE` nếu muốn một client duy nhất); device object trả ra được cấp phát từ non-paged pool.
- Tên device khởi tạo bằng `RTL_CONSTANT_STRING(L"\\Device\\Booster")` — tính độ dài lúc compile (chỉ dùng cho literal), nhanh hơn `RtlInitUnicodeString` vốn đếm ký tự lúc chạy.
- Tạo symbolic link `\??\Booster` bằng `IoCreateSymbolicLink`; thất bại phải `IoDeleteDevice` ngay: nếu `DriverEntry` trả status lỗi thì Unload không được gọi, mọi bước đã làm phải tự undo theo thứ tự ngược.
- Unload làm ngược lại: `IoDeleteSymbolicLink` rồi `IoDeleteDevice(DriverObject->DeviceObject)`; lấy device object từ driver object thay vì biến global.

### Client Code
- Console app tên Boost, include `<windows.h>`, `<stdio.h>`, `..\Booster\BoosterCommon.h`; `main` nhận thread ID và priority từ command line.
- `CreateFile(L"\\\\.\\Booster", GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr)` — symbolic link với tiền tố `\\.\`; driver chưa nạp thì gặp error 2 (file not found). Lời gọi tới `IRP_MJ_CREATE`.
- Điền `ThreadData` rồi `WriteFile(hDevice, &data, sizeof(data), &returned, nullptr)` (tới `IRP_MJ_WRITE`), cuối cùng `CloseHandle`.

### The Create and Close Dispatch Routines
- Chỉ cần hoàn tất IRP thành công: `Irp->IoStatus.Status = STATUS_SUCCESS`, `Information = 0`, `IoCompleteRequest(Irp, IO_NO_INCREMENT)`, return `STATUS_SUCCESS`.
- IRP là struct bán-tài-liệu-hóa đại diện request từ các manager (I/O, Plug & Play, Power Manager); luôn kèm một hoặc nhiều `IO_STACK_LOCATION` — mỗi layer trong device stack một cái.
- `IO_STATUS_BLOCK` có `Status` (NTSTATUS) và `Information` (`ULONG_PTR` đa nghĩa; với Create/Close dùng 0). `IoCompleteRequest` trả IRP về người tạo, thông báo client, giải phóng IRP; tham số 2 là priority boost tạm, dùng `IO_NO_INCREMENT` (=0) với request đồng bộ.
- Phải return cùng status với status trong IRP — trông thừa nhưng bắt buộc.

### The Write Dispatch Routine
- Lấy `IO_STACK_LOCATION` hiện tại bằng `IoGetCurrentIrpStackLocation`; thông số riêng từng loại IRP nằm trong union `Parameters`, với write là `Parameters.Write.Length`.
- Dùng khối `do { … } while (false)` với `break` để thoát sớm khi lỗi: `Length < sizeof(ThreadData)` → `STATUS_BUFFER_TOO_SMALL`.
- Lấy buffer từ `Irp->UserBuffer`, cast sang `ThreadData*`; kiểm tra NULL trước rồi mới kiểm tra priority 1..31 (short-circuit evaluation), sai → `STATUS_INVALID_PARAMETER`.
- `PsLookupThreadByThreadId(ULongToHandle(data->ThreadId), &thread)` trả `PETHREAD` (cần `#include <ntifs.h>` đặt trước `<ntddk.h>`); thất bại thường do thread ID không tồn tại. Hoán đổi được `PETHREAD`/`PKTHREAD` vì thành viên đầu của `ETHREAD` là `KTHREAD` (tên `Tcb`).
- Lookup thành công tăng reference count nên thread không thể biến mất trước khi đổi priority; sau `KeSetPriorityThread` (trả priority cũ) bắt buộc `ObDereferenceObject`, nếu không thread object leak cho tới lần boot sau.
- Gán `information = sizeof(data)` báo số byte đã dùng (client nhận qua `lpNumberOfBytesWritten`), rồi hoàn tất IRP với status hiện có. Lưu ý: đoạn code trung gian trong sách đặt tên `BoosterDeviceControl` nhưng handler hoàn chỉnh cuối là `BoosterWrite`.

### Installing and Testing
- Cài: `sc create booster type= kernel binPath= c:\Test\Booster.sys` (binPath là full path; "booster" là tên Registry key, phải duy nhất, không cần khớp tên SYS); nạp bằng `sc start booster`.
- Kiểm chứng bằng WinObj (thấy device và symbolic link); chạy client, ví dụ `boost 768 25`.
- Client bản Debug có thể phải đổi Runtime Library sang static (Multithreaded Debug) hoặc dùng bản Release; xem output `KdPrint` bằng DbgView.

## API / cấu trúc / hằng số quan trọng

| Tên | Loại | Vai trò & ghi chú ngắn |
|---|---|---|
| `DriverEntry` | hàm | Điểm vào driver; đặt Unload, dispatch routines, tạo device object và symbolic link |
| `SetPriorityClass` / `SetThreadPriority` | hàm | API user-mode bị giới hạn: 6 priority class, offset −2..+2 cộng 2 mức saturation |
| `IoCreateDevice` | hàm | Tạo `DEVICE_OBJECT` từ non-paged pool; software driver dùng `FILE_DEVICE_UNKNOWN` |
| `IoCreateSymbolicLink` / `IoDeleteSymbolicLink` | hàm | Tạo/xóa liên kết `\??\Booster` → `\Device\Booster` để client mở bằng `CreateFile` |
| `IoDeleteDevice` | hàm | Hủy device object khi khởi tạo lỗi hoặc khi unload |
| `IoGetCurrentIrpStackLocation` | hàm | Lấy `IO_STACK_LOCATION` của layer hiện tại; chứa `Parameters.Write.Length` |
| `IoCompleteRequest` | hàm | Hoàn tất IRP, trả về I/O Manager; tham số 2: `IO_NO_INCREMENT` (=0) |
| `PsLookupThreadByThreadId` | hàm | Tra `PETHREAD` từ thread ID (truyền dạng `HANDLE`); tăng reference count |
| `KeSetPriorityThread` | hàm | Đặt priority (`KPRIORITY`, số nguyên 8-bit) cho `PKTHREAD`; trả priority cũ |
| `ObDereferenceObject` | hàm | Giảm reference count sau khi dùng; thiếu là leak thread object |
| `RTL_CONSTANT_STRING` | macro | Khởi tạo `UNICODE_STRING`, tính độ dài lúc compile, chỉ dùng cho literal |
| `RtlInitUnicodeString` | hàm | Khởi tạo `UNICODE_STRING` bằng cách đếm ký tự lúc chạy |
| `IRP` | struct | Bọc mọi request; chứa `IoStatus` (`IO_STATUS_BLOCK`) và `UserBuffer` |
| `IO_STACK_LOCATION` | struct | Kèm theo IRP cho từng layer; chứa union `Parameters` |
| `IO_STATUS_BLOCK` | struct | `Status` (NTSTATUS) + `Information` (`ULONG_PTR` đa nghĩa) |
| `ThreadData` | struct | `{ ULONG ThreadId; int Priority; }` — giao thức chung client/driver |
| `ETHREAD` / `KTHREAD` | struct | `KTHREAD Tcb` là thành viên đầu của `ETHREAD`; `PETHREAD`/`PKTHREAD` hoán đổi được |
| `UNICODE_STRING` | struct | Chuỗi kernel; khởi tạo bằng `RTL_CONSTANT_STRING` hoặc `RtlInitUnicodeString` |
| `IRP_MJ_CREATE` / `IRP_MJ_CLOSE` / `IRP_MJ_WRITE` | hằng số | Chỉ số mảng `MajorFunction` cho mở handle, đóng handle và write |
| `STATUS_BUFFER_TOO_SMALL` / `STATUS_INVALID_PARAMETER` | hằng số | Buffer thiếu kích thước / buffer NULL hoặc priority ngoài 1..31 |
| `FILE_DEVICE_UNKNOWN` | hằng số | Device type chuẩn cho software driver |

## Code / mẫu thiết kế đáng nhớ

Hoàn tất IRP cho Create/Close — mẫu tối thiểu cho dispatch routine chỉ cần "approve" request:

```c
NTSTATUS BoosterCreateClose(PDEVICE_OBJECT DeviceObject, PIRP Irp) {
    UNREFERENCED_PARAMETER(DeviceObject);
    Irp->IoStatus.Status = STATUS_SUCCESS;
    Irp->IoStatus.Information = 0;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return STATUS_SUCCESS;
}
```

Handler `IRP_MJ_WRITE` hoàn chỉnh — mẫu validate input bằng `do/while(false)`, lookup thread, đổi priority và giải phóng reference:

```c
NTSTATUS BoosterWrite(PDEVICE_OBJECT, PIRP Irp) {
    auto status = STATUS_SUCCESS;
    ULONG_PTR information = 0;
    auto irpSp = IoGetCurrentIrpStackLocation(Irp);
    do {
        if (irpSp->Parameters.Write.Length < sizeof(ThreadData)) {
            status = STATUS_BUFFER_TOO_SMALL;
            break;
        }
        auto data = static_cast<ThreadData*>(Irp->UserBuffer);
        if (data == nullptr || data->Priority < 1 || data->Priority > 31) {
            status = STATUS_INVALID_PARAMETER;
            break;
        }
        PETHREAD thread;
        status = PsLookupThreadByThreadId(
            ULongToHandle(data->ThreadId), &thread);
        if (!NT_SUCCESS(status)) {
            break;
        }
        auto oldPriority = KeSetPriorityThread(thread, data->Priority);
        KdPrint(("Priority change for thread %u from %d to %d succeeded!\n",
            data->ThreadId, oldPriority, data->Priority));
        ObDereferenceObject(thread);
        information = sizeof(data);
    } while (false);
    Irp->IoStatus.Status = status;
    Irp->IoStatus.Information = information;
    IoCompleteRequest(Irp, IO_NO_INCREMENT);
    return status;
}
```

Client mở device và gửi dữ liệu — mẫu giao tiếp cơ bản với software driver qua symbolic link:

```c
HANDLE hDevice = CreateFile(L"\\\\.\\Booster", GENERIC_WRITE,
    0, nullptr, OPEN_EXISTING, 0, nullptr);
ThreadData data;
data.ThreadId = tid;
data.Priority = priority;
DWORD returned;
BOOL success = WriteFile(hDevice, &data, sizeof(data), &returned, nullptr);
CloseHandle(hDevice);
```

## Cạm bẫy & lưu ý

- Sau `IoCompleteRequest`, con trỏ IRP phải coi là "poison" — rất có thể đã bị giải phóng; viết `return Irp->IoStatus.Status;` sau lời gọi này gây BSOD trong phần lớn trường hợp.
- Nếu `DriverEntry` trả status thất bại, Unload không được gọi; phải tự undo các bước đã làm (ví dụ `IoDeleteDevice` khi `IoCreateSymbolicLink` thất bại) theo thứ tự ngược.
- Quên `ObDereferenceObject` sau `PsLookupThreadByThreadId` gây leak thread object vĩnh viễn (chỉ hết khi reboot).
- `#include <ntifs.h>` phải đặt trước `<ntddk.h>` (hoặc bỏ `<ntddk.h>` vì `ntifs.h` đã include nó), nếu không lỗi compile.
- Kiểm tra NULL trước khi dereference, tận dụng short-circuit evaluation; buffer có thể NULL dù length > 0.
- Priority class Real-time cần quyền administrator, nếu không bị đổi thành High.
- Client bản Debug có thể cần Runtime Library static (Multithreaded Debug); bản Release chạy không cần chỉnh.

## Tóm lại cần nhớ

- Software driver hoàn chỉnh gồm: `DriverEntry` làm 4 việc (Unload routine, dispatch routines, device object, symbolic link) và Unload làm ngược lại đúng thứ tự.
- Mọi request đều bọc trong IRP kèm `IO_STACK_LOCATION`; xử lý xong phải đặt `IoStatus`, gọi `IoCompleteRequest` và return đúng status.
- Client giao tiếp qua `CreateFile`/`WriteFile` tới symbolic link `\\.\Booster`; định dạng dữ liệu chia sẻ bằng header chung (`BoosterCommon.h`).
- Chuỗi đặt priority từ kernel: `PsLookupThreadByThreadId` → `KeSetPriorityThread` → `ObDereferenceObject`, luôn validate input từ user mode trước.
- Chương sau chuyển sang debugging — kỹ năng tất yếu khi driver không chạy như mong đợi.
