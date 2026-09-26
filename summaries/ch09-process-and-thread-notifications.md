# Chương 9: Process and Thread Notifications

> Nguồn: *Windows Kernel Programming, 2nd Edition* — Pavel Yosifovich, trang 268–312

## Tổng quan

Chương giới thiệu các callback của kernel thông báo cho driver theo thời gian thực ("in-line") khi process tạo/kết thúc, thread tạo/kết thúc và khi PE image được nạp. Đây là nền tảng của các công cụ giám sát kiểu Sysinternals SysMon, và chỉ driver kernel mới có quyền **chặn** việc tạo process. Chương xây dựng driver SysMon (lưu event vào linked list, đưa data lên user mode qua read) và driver KDetector phát hiện remote thread.

## Nội dung theo từng mục

### Process Notifications
- Notification gửi "in-line" khi tạo/kết thúc nên không bỏ sót process sống ngắn; ETW ở user mode trễ 1–3 giây (buffer nội bộ) và không chặn được tạo process.
- Đăng ký `PsSetCreateProcessNotifyRoutineEx(NotifyRoutine, Remove)` — tối đa 64 đăng ký toàn hệ thống; `FALSE` khi đăng ký trong `DriverEntry`, `TRUE` khi hủy trong Unload.
- Callback `(PEPROCESS, HANDLE ProcessId, PPS_CREATE_NOTIFY_INFO CreateInfo)`; `CreateInfo` là `NULL` khi exit. Callback chạy trên thread tạo process (khi tạo) hoặc thread cuối rời process (khi exit), luôn trong critical region (normal kernel APCs disabled).
- Từ Windows 10 1607, `PsSetCreateProcessNotifyRoutineEx2` nhận thêm Pico processes (WSL v1).
- Driver phải đặt flag `IMAGE_DLLCHARACTERISTICS_FORCE_INTEGRITY` (linker `/integritycheck`), nếu không nhận `STATUS_ACCESS_DENIED`.
- `PS_CREATE_NOTIFY_INFO`: `CreatingThreadId`, `ParentProcessId`, `ImageFileName` (khi `FileOpenNameAvailable`), `CommandLine` (có thể `NULL`), `IsSubsystemProcess`, `CreationStatus` — ghi mã lỗi (vd. `STATUS_ACCESS_DENIED`) vào đây để chặn tạo; driver đăng ký sau sẽ không được gọi.

### Implementing Process Notifications
- SysMon lưu event vào linked list bảo vệ bằng fast mutex; class `Globals` giữ `m_ItemsHead`, `m_Count`, `m_MaxCount` (giới hạn 10000, chống list phình vô hạn), `m_Lock`.
- Struct chia sẻ user mode đặt trong `SysMonPublic.h`: `enum class ItemType : short` và `ItemHeader { Type; Size; Time; }` — `Size` cho biết event kế tiếp bắt đầu ở đâu.
- `ProcessExitInfo` kế thừa `ItemHeader`, thêm `ProcessId`, `ExitCode`; ID dùng `ULONG` (không quá 32-bit; tránh `HANDLE` vì khác nhau giữa 32/64-bit).
- `LIST_ENTRY` không lộ ra user mode → template `FullItem<T> { LIST_ENTRY Entry; T Data; }` (cách khác: union các variant); không kế thừa `LIST_ENTRY` vì thiếu tự nhiên.

### The DriverEntry Routine
- Tạo device exclusive, `DO_DIRECT_IO`, symlink `\??\sysmon`, đăng ký callback; lỗi thì dọn dẹp; `g_State.Init(10000)`; create/close hoàn thành IRP qua `CompleteRequest`.
- Bài tập: đọc giới hạn item từ registry (`ZwOpenKey`/`IoOpenDeviceRegistryKey` + `ZwQueryValueKey`).

### Handling Process Exit Notifications
- Cấp phát `FullItem<ProcessExitInfo>` bằng `ExAllocatePoolWithTag(PagedPool, ..., DRIVER_TAG)`; lỗi cấp phát thì chỉ thoát.
- Header: `KeQuerySystemTimePrecise` (Win8+, trước đó `KeQuerySystemTime`), UTC 64-bit từ 1/1/1601; `Size` là kích thước struct user-facing; dùng reference (`auto& item`) tránh copy.
- `HandleToULong` cho process ID; exit code lấy bằng `PsGetProcessExitStatus(Process)`.
- `Globals::AddItem` giữ fast mutex (qua `Locker`, cần C++ 17); nếu đầy thì bỏ item đầu (`ExFreePool`); luôn `InsertTailList`; không cần atomic vì đếm dưới khóa.

### Handling Process Create Notifications
- Command line đổi độ dài: mảng cố định `WCHAR[1024]` phải cắt nếu dài hoặc lãng phí nếu ngắn; `UNICODE_STRING` không dùng được (user mode không có định nghĩa, pointer trỏ system space, không rõ free).
- Giải pháp: `CommandLineLength` (số `WCHAR`) + flexible array `WCHAR CommandLine[1]`; cấp phát `sizeof(FullItem<ProcessCreateInfo>) + commandLineSize`, `memcpy`, `Size` tính cả command line.
- Lưu thêm `ParentProcessId`, `CreatingProcessId`, `CreatingThreadId`; command line không có NUL (bài tập: thêm NUL, bỏ độ dài; kích thước cấp phát thừa đúng 1 ký tự cho NUL).

### Providing Data to User Mode
- Client poll bằng IRP read; driver lấp buffer user với càng nhiều event càng tốt — hết buffer hoặc hết queue thì dừng.
- `SysMonRead`: buffer Direct I/O qua `MmGetSystemAddressForMdlSafe(Irp->MdlAddress, NormalPagePriority)`; lỗi trả `STATUS_INSUFFICIENT_RESOURCES`.
- Vòng lặp: `RemoveItem` lấy đầu list dưới khóa → `CONTAINING_RECORD`; buffer không đủ chỗ cho item thì `AddHeadItem` đẩy lại rồi dừng; đủ thì `memcpy` phần `Data` (không kèm `LIST_ENTRY`), `ExFreePool`; hoàn tất IRP với số byte đã copy.
- `SysMonUnload` hủy đăng ký callback và xả hết item còn lại (nếu không leak), xóa symlink/device.

### The User Mode Client
- Mở `\\.\SysMon`, `ReadFile` vòng lặp với buffer 64 KB, `Sleep(400)` giữa các lần poll.
- `DisplayInfo` đọc `ItemHeader`, `switch` theo `Type`, tiến `buffer += header->Size`; create dựng `std::wstring` từ pointer + độ dài; `DisplayTime` chuyển UTC → local qua `FileTimeToLocalFileTime` + `FileTimeToSystemTime`.
- Cài thử: `sc create sysmon type= kernel binPath=...`, `sc start sysmon`.

### Thread Notifications
- `PsSetCreateThreadNotifyRoutine` / `PsRemoveCreateThreadNotifyRoutine`; callback `(HANDLE ProcessId, HANDLE ThreadId, BOOLEAN Create)`.
- Khi tạo, callback chạy trên thread tạo ra nó; khi exit, trên chính thread đó.
- SysMon thêm `ThreadCreate`/`ThreadExit`; `ThreadExitInfo` kế thừa `ThreadCreateInfo` (chung `ThreadId`, `ProcessId`) cộng `ExitCode`.
- Exit code: `PsGetThreadExitStatus` cần `PETHREAD` → `PsLookupThreadByThreadId` rồi bắt buộc `ObDereferenceObject` (nếu không, thread object tồn tại đến khi restart).
- `PsSetCreateThreadNotifyRoutineEx(NotifyType, ...)` với `PSCREATETHREADNOTIFYTYPE`: `PsCreateThreadNotifyNonSystem` chạy callback trên chính thread mới; `PsCreateThreadNotifySubsystems` cho subsystem processes.

### Image Load Notifications
- Callback đăng ký qua `PsSetLoadImageNotifyRoutine` (hủy: `PsRemoveLoadImageNotifyRoutine`) chạy với `(FullImageName, ProcessId, PIMAGE_INFO)` khi PE image (EXE/DLL/driver) nạp; không có notification cho image unload.
- `FullImageName` có thể `NULL`, trước Windows 10 không phải lúc nào cũng đúng; đường dẫn dạng NT (`\Device\HarddiskVolume3\...`); `ProcessId` = 0 với kernel image.
- `IMAGE_INFO`: bitfield `SystemModeImage`, `ExtendedInfoPresent`, `SignatureLevel`/`SignatureType` (PPL, Win8.1+), cùng `ImageBase`, `ImageSize`; nếu `ExtendedInfoPresent` → `IMAGE_INFO_EX` qua `CONTAINING_RECORD` để lấy `FileObject`.
- SysMon thêm `ImageLoad` và `ImageLoadInfo` với mảng cố định `WCHAR ImageFileName[301]`; bỏ qua kernel image khi `ProcessId` NULL.
- Lấy tên tin cậy: `FltGetFileNameInformationUnsafe(FileObject, nullptr, FLT_FILE_NAME_NORMALIZED | FLT_FILE_NAME_QUERY_DEFAULT, ...)` rồi `FltReleaseFileNameInformation`; cần `FltKernel.h` + `FltMgr.lib`; trống thì fallback sang `FullImageName`.
- `DriverEntry` đăng ký cả ba callback, dùng cờ để gỡ đúng những gì đã đăng ký khi lỗi giữa chừng.

### Final Client Code
- Đường dẫn trả về dạng NT device; ký tự ổ đĩa là symbolic link trong thư mục "??" (xem bằng WinObj).
- `GetDosNameFromNTName`: `GetLogicalDrives` + `QueryDosDevice` map tên device → ký tự ổ (lưu `std::unordered_map`, dựng một lần); không khớp trả chuỗi gốc. Bài tập: thêm tên process vào image load; viết driver chặn thực thi exe theo danh sách cấm.

### Remote Thread Detection
- Remote thread: thread được inject vào process khác process tạo ra nó — cơ chế DLL injection; không hẳn độc hại: debugger break vào target bằng cách tạo thread gọi `DebugBreak`.
- Ý tưởng: so sánh creator PID (`PsGetCurrentProcessId()`) với PID đích. Ngoại lệ: thread đầu tiên của mọi process luôn "remote" theo định nghĩa (do process khác gọi `CreateProcess`).
- KDetector lưu `RemoteThread { Time, CreatorProcessId, CreatorThreadId, ProcessId, ThreadId }` (dùng chung client) trong `RemoteThreadItem { LIST_ENTRY Link; ... }`, cấp phát từ `LookasideList<RemoteThreadItem>`.
- Trạng thái: `NewProcesses[32]` theo dõi process chưa có thread, bảo vệ bằng `ExecutiveResource` (wrapper ERESOURCE, hợp đọc nhiều hơn ghi; nếu `KeAreApcsDisabled()` thì acquire trực tiếp, ngược lại `ExEnterCriticalRegionAndAcquireResourceExclusive/Shared`; shared lock qua `SharedLocker<TLock>`); list `RemoteThreadsHead` khóa bằng `FastMutex`.
- Logic: process mới → `AddNewProcess`; thread tạo: `remote = PsGetCurrentProcessId() != ProcessId && PsInitialSystemProcess != PsGetCurrentProcess() && PsGetProcessId(PsInitialSystemProcess) != ProcessId` — loại false positive từ System process (nhận diện bằng `PsInitialSystemProcess` thay vì PID 4).
- Remote mà `FindProcess` thấy trong mảng → thread đầu tiên, `RemoveProcess` để lần sau tính là remote thật; không thấy → remote thật: lấy item từ lookaside, điền 4 ID + thời gian, `InsertTailList`.
- `DetectorRead` đơn giản hơn (event cố định kích thước): lặp khi list không rỗng và `len >= sizeof(RemoteThread)`, `RemoveHeadList` + `memcpy`, trả item về lookaside.

### The Detector Client
- Mở `\\.\kdetector`, đọc vào mảng `RemoteThread rt[20]`, hiển thị `bytes / sizeof(RemoteThread)` phần tử, `Sleep(1000)`.
- Kiểm thử: chạy Notepad rồi attach WinDbg — mỗi lần break sinh một notification; thực tế có thể thấy entry bất ngờ từ process khác.

## API / cấu trúc / hằng số quan trọng

| Tên | Loại | Vai trò & ghi chú ngắn |
|---|---|---|
| `PsSetCreateProcessNotifyRoutineEx` | hàm | Đăng ký/hủy callback process; cần FORCE_INTEGRITY; tối đa 64 đăng ký |
| `PsSetCreateProcessNotifyRoutineEx2` | hàm | Như trên, thêm Pico processes (Win10 1607+) |
| `PS_CREATE_NOTIFY_INFO` | struct | Chi tiết process tạo; `CreationStatus` dùng để chặn tạo |
| `PsSetCreateThreadNotifyRoutine` / `PsRemoveCreateThreadNotifyRoutine` | hàm | Đăng ký/hủy callback thread |
| `PsSetCreateThreadNotifyRoutineEx` | hàm | Nhận `PSCREATETHREADNOTIFYTYPE`; `PsCreateThreadNotifyNonSystem` chạy callback trên thread mới |
| `PsSetLoadImageNotifyRoutine` / `PsRemoveLoadImageNotifyRoutine` | hàm | Đăng ký/hủy callback image load |
| `IMAGE_INFO` / `IMAGE_INFO_EX` | struct | `SystemModeImage`, `ImageBase`, `ImageSize`, `ExtendedInfoPresent`; EX thêm `FileObject` |
| `PsGetProcessExitStatus` / `PsGetThreadExitStatus` | hàm | Exit code từ `PEPROCESS` / `PETHREAD` |
| `PsLookupThreadByThreadId` | hàm | `PETHREAD` từ ID; phải `ObDereferenceObject` |
| `PsInitialSystemProcess` | biến | EPROCESS của System process — nhận diện không cần dựa PID 4 |
| `KeQuerySystemTimePrecise` | hàm | Thời gian UTC 64-bit (từ 1/1/1601); Win8+ |
| `FltGetFileNameInformationUnsafe` / `FltReleaseFileNameInformation` | hàm | Tên file normalized từ `FileObject` (cần `FltKernel.h` + `FltMgr.lib`) / giải phóng kết quả |
| `FullItem<T>` | struct (template) | Thêm `LIST_ENTRY` trước dữ liệu event để lưu linked list |
| `ItemHeader` / `ItemType` | struct / enum | Header chung mọi event (Type/Size/Time) chia sẻ driver–user mode |
| `ExecutiveResource` | struct (wrapper) | Bọc ERESOURCE, tự xử lý critical region; có shared lock |
| `LookasideList<T>` | struct (wrapper) | Bọc lookaside list cho cấp phát fixed-size nhanh |
| `QueryDosDevice` | hàm (user mode) | Map tên NT device → ký tự ổ đĩa |
| `HandleToULong` | macro | Ép HANDLE (ID) sang ULONG an toàn theo bitness |

## Code / mẫu thiết kế đáng nhớ

Khối 1 — command line biến đổi độ dài trong process create callback (flexible array + trường độ dài):

```cpp
USHORT allocSize = sizeof(FullItem<ProcessCreateInfo>);
USHORT commandLineSize = 0;
if (CreateInfo->CommandLine) {
    commandLineSize = CreateInfo->CommandLine->Length;
    allocSize += commandLineSize;
}
auto info = (FullItem<ProcessCreateInfo>*)ExAllocatePoolWithTag(
    PagedPool, allocSize, DRIVER_TAG);
// fill header, sau đó:
memcpy(item.CommandLine, CreateInfo->CommandLine->Buffer, commandLineSize);
item.CommandLineLength = commandLineSize / sizeof(WCHAR);
```

Khối 2 — xả queue event vào buffer Direct I/O trong read dispatch:

```cpp
while (true) {
    auto entry = g_State.RemoveItem();
    if (entry == nullptr) break;
    auto info = CONTAINING_RECORD(entry, FullItem<ItemHeader>, Entry);
    auto size = info->Data.Size;
    if (len < size) { g_State.AddHeadItem(entry); break; } // buffer đầy, đẩy lại
    memcpy(buffer, &info->Data, size);
    len -= size; buffer += size; bytes += size;
    ExFreePool(info);
}
return CompleteRequest(Irp, status, bytes);
```

Khối 3 — nhận diện remote thread (loại false positive System process và thread đầu tiên):

```cpp
bool remote = PsGetCurrentProcessId() != ProcessId
    && PsInitialSystemProcess != PsGetCurrentProcess()
    && PsGetProcessId(PsInitialSystemProcess) != ProcessId;
if (remote) {
    if (FindProcess(ProcessId))
        RemoveProcess(ProcessId);   // thread đầu tiên của process mới
    else { /* remote thật: ghi nhận từ lookaside vào list */ }
}
```

## Cạm bẫy & lưu ý

- Thiếu `/integritycheck` (FORCE_INTEGRITY) → `STATUS_ACCESS_DENIED` khi đăng ký; giới hạn 64 đăng ký toàn hệ thống.
- Sau `PsLookupThreadByThreadId` bắt buộc `ObDereferenceObject`; sau `FltGetFileNameInformationUnsafe` phải `FltReleaseFileNameInformation` — nếu không leak object đến khi restart.
- Item cấp phát động trong linked list phải giải phóng trong Unload, nếu không leak.
- Callback process/thread chạy trong critical region; ERESOURCE phải acquire trong critical region (wrapper kiểm tra `KeAreApcsDisabled`).
- Không đưa `UNICODE_STRING`, `HANDLE`, `LIST_ENTRY` vào struct chia sẻ với user mode; command line trong event không có NUL — client phải đọc đúng độ dài.
- `FullImageName` có thể `NULL`, không đáng tin trước Windows 10; đường dẫn NT cần chuyển sang DOS bằng `QueryDosDevice`; `ProcessId` = 0/NULL là kernel image.
- Thread đầu tiên của process mới luôn trông như remote thread — phải theo dõi process mới để loại false positive.

## Tóm lại cần nhớ

- Kernel callback in-line cho process/thread/image load: không bỏ sót event (khác ETW trễ 1–3 giây) và chỉ driver chặn được tạo process qua `CreationStatus`; image load không có notification cho unload.
- Mẫu kiến trúc giám sát: event có `ItemHeader` (Type/Size/Time) chung driver–user mode, linked list giới hạn phần tử bảo vệ bằng fast mutex, client poll bằng ReadFile (Direct I/O + MDL), duyệt buffer nhờ trường `Size`.
- Dữ liệu biến đổi độ dài (command line) dùng flexible array + trường độ dài; dữ liệu fixed-size tần suất cao hợp lý với lookaside list.
- Remote thread detection chỉ là so sánh `PsGetCurrentProcessId()` với PID đích, cộng việc loại false positive: thread đầu tiên của process mới và các trường hợp từ System process (`PsInitialSystemProcess`).
- Chương sau: callback mở handle tới object và registry notifications.
