# Chương 8: Advanced Programming Techniques (Part 1)

> Nguồn: *Windows Kernel Programming, 2nd Edition* — Pavel Yosifovich, trang 230–267

## Tổng quan

Chương này giới thiệu các kỹ thuật nâng cao dùng cho nhiều loại driver: tạo thread do driver sở hữu cho thao tác dài, cấp phát bộ nhớ mở rộng (priority allocation, secure pool, overload `new`/`delete`, lookaside lists), gọi driver khác bằng cách tự dựng IRP, và gọi system service không được document. Tất cả được tổng hợp trong driver mẫu KMelody phát nhạc bất đồng bộ qua Beep device.

## Nội dung theo từng mục

### Driver Created Threads
- Work items (chương 6) chỉ hợp với mã chạy ngắn; thao tác dài nên dùng thread riêng: `PsCreateSystemThread` hoặc `IoCreateSystemThread` (Windows 8+).
- `IoCreateSystemThread` nhận thêm device/driver object ở tham số đầu và tự giữ reference, nên driver không bị unload khi thread còn sống; nó bọc `PsCreateSystemThread`, và khi hàm thread return sẽ tự gọi `PsTerminateSystemThread` (exit code `STATUS_SUCCESS`) rồi giảm ref count.
- Thread chạy ở `PASSIVE_LEVEL` (0) trong critical region (normal kernel APCs disabled). Nên truyền `ProcessHandle = NULL` để thread thuộc System process; `DesiredAccess` dùng `THREAD_ALL_ACCESS`, handle trả về phải đóng bằng `ZwClose`, `ObjectAttributes`/`ClientId` thường NULL.
- Khác biệt then chốt: với `PsCreateSystemThread`, thoát khỏi hàm thread chưa đủ — phải gọi tường minh `PsTerminateSystemThread` (exit status đọc qua `PsGetThreadExitStatus`).

### Memory Management

#### Pool Allocations
- `ExAllocatePoolWithTagPriority` thêm `EX_POOL_PRIORITY` (Low/Normal/High, mỗi mức có biến thể `SpecialPoolOverrun`/`Underrun`) báo độ quan trọng khi bộ nhớ thấp; vẫn phải xử lý thất bại.
- Special pool đặt block ở cuối (Overrun) hoặc đầu (Underrun) trang để bắt buffer overflow/underflow — chỉ dùng khi truy vết memory corruption vì mỗi lần cấp tốn ít nhất một trang.
- Từ Windows 10 1909: `ExAllocatePool2` với cờ `POOL_FLAG_*` (`USE_QUOTA`, `UNINITIALIZED` — không có thì memory bị zero, `CACHE_ALIGNED`, `RAISE_ON_FAILURE`, `NON_PAGED`, `PAGED`, `NON_PAGED_EXECUTABLE`, `SPECIAL_POOL`); cờ "must recognize" không thỏa mãn làm hàm thất bại. Memory chỉ executable trên x86.
- `ExAllocatePool3` mở rộng qua mảng `POOL_EXTENDED_PARAMETER` (`Type`, bit `Optional`, union chứa `Priority`/`SecurePoolParams`/`PreferredNode`); tham số optional không thỏa mãn không gây thất bại, và nhờ đó không cần hàm cấp phát mới trong tương lai.

#### Secure Pools
- Secure pool (Windows 10 1909+) là vùng memory kernel component khác không truy cập được; bảo vệ thật sự bằng Hyper-V vì memory thuộc VTL 1 (secure world); chỉ có khi Virtualization Based Security (VBS) bật.
- Tạo bằng `ExCreatePool` (cờ `POOL_CREATE_FLG_SECURE_POOL` | `POOL_CREATE_FLG_USE_GLOBAL_POOL`), hủy bằng `ExDestroyPool`.
- Cấp phát phải dùng `ExAllocatePool3` với `POOL_EXTENDED_PARAMS_SECURE_POOL` (pool handle, `Buffer` dữ liệu khởi tạo, `Cookie` kiểm chứng bằng `ExSecurePoolValidate`, cờ `SECURE_POOL_FLAGS_*`); giải phóng bằng `ExFreePool2` kèm extended parameter chứa pool handle — truyền NULL thì rơi về `ExFreePool` và thất bại với secure pool.

#### Overloading the new and delete Operators
- Kernel không có C++ runtime nên `new`/`delete` mặc định không dùng được; overload chúng cho phép chạy constructor/destructor và cấp phát theo kiểu.
- Overload chuẩn: `operator new(size_t, POOL_TYPE pool, ULONG tag)` gọi `ExAllocatePoolWithTag`; compiler tự chèn `size`, tham số còn lại viết trong ngoặc (`new (PagedPool, DRIVER_TAG) MyData`), tag có thể default, constructor nào cũng gọi được (`new (PagedPool) MyData(200)`).
- Biến thể: overload bọc `ExAllocatePoolWithTagPriority` (`new (PagedPool, LowPoolPriority) MyData(200)`); placement new `operator new(size_t, void*)` chỉ trả con trỏ có sẵn để chạy constructor trên block đã cấp phát.
- Cần `operator delete(void* p, size_t)` gọi `ExFreePool` (tham số size luôn 0 nhưng compiler bắt buộc); conformance C++17+ có thể đòi thêm overload với `std::align_val_t`. `__cdecl` chỉ ảnh hưởng trên x86 nhưng vẫn nên ghi.

#### Lookaside Lists

##### The "Classic" Lookaside API
- Pool generic tốn chi phí quản lý; với block cố định kích thước, lookaside list không giải phóng block thật mà đánh dấu "rảnh" để tái sử dụng — nhanh hơn hẳn.
- Khởi tạo: `ExInitializePagedLookasideList` / `ExInitializeNPagedLookasideList`; có thể cung cấp hàm Allocate/Free riêng (mặc định `ExAllocatePoolWithTag`/`ExFreePool`), `Flags` = 0 hoặc `POOL_RAISE_IF_ALLOCATION_FAILURE` (Windows 8+), `Depth` là reserved (để 0, manager tự điều chỉnh); struct coi như opaque.
- Dùng `ExAllocateFromPagedLookasideList` / `ExFreeToPagedLookasideList` (có biến thể NPaged); xong thì `ExDeletePagedLookasideList` — tự giải phóng mọi block còn lại, không cần trả từng block.

##### The Newer Lookaside API
- API mới (`LOOKASIDE_LIST_EX`, từ Vista): thống nhất paged/non-paged, và truyền chính struct lookaside vào hàm allocate/free tùy chọn — lấy driver context bằng `CONTAINING_RECORD` khi list nằm trong struct lớn.
- `ExInitializeLookasideListEx`; struct phải nằm trong non-paged memory bất kể list quản lý pool gì. `Flags`: `EX_LOOKASIDE_LIST_EX_FLAGS_RAISE_ON_FAIL` hoặc `..._FAIL_NO_RAISE` (chỉ hợp lệ khi có custom allocator) — hai cờ loại trừ nhau.
- Cấp phát/giải phóng/hủy: `ExAllocateFromLookasideListEx`, `ExFreeToLookasideListEx`, `ExDeleteLookasideListEx`.

### Calling Other Drivers
- Ngoài cách làm client chuẩn (`ZwOpenFile`/`ZwCreateFile`), driver có thể tự dựng IRP gửi thẳng tới device object — hiệu quả hơn mở handle, và đôi khi chỉ lấy được con trỏ device chứ không mở được handle.
- `IoBuildDeviceIoControlRequest` dựng IRP device control hoàn chỉnh (điền `IO_STACK_LOCATION` đầu): tham số giống `DeviceIoControl` (`IoControlCode`, input/output buffer) cộng `DeviceObject` đích, `InternalDeviceIoControl` (TRUE → `IRP_MJ_INTERNAL_DEVICE_CONTROL`, FALSE → `IRP_MJ_DEVICE_CONTROL`), `Event` tùy chọn được signal khi IRP hoàn thành (cần nếu chờ đồng bộ), `IoStatusBlock` nhận kết quả.
- Hàm này chỉ dựng IRP; gửi bằng `IoCallDriver`: chuyển stack location kế thành current, gán device object, gọi dispatch routine trong `MajorFunction[]` và trả kết quả của nó.
- Lấy device object: `IoGetDeviceObjectPointer` (tên đầy đủ trong Object Manager namespace; access như `FILE_READ_DATA`/`FILE_WRITE_DATA`/`FILE_ALL_ACCESS`). Phải giữ `FILE_OBJECT` trả về để giữ reference cho device; xong gọi `ObDereferenceObject` trên file object (hoặc `ObReferenceObject` device rồi bỏ file object).

### Putting it All Together: The Melody Driver
- KMelody phát chuỗi nốt bất đồng bộ (`Beep` user-mode là đồng bộ): client gửi mảng `Note` (`Frequency`, `Duration`, `Delay`, `Repeat`; ms) qua `IOCTL_MELODY_PLAY` (`CTL_CODE`, `METHOD_BUFFERED`, `FILE_ANY_ACCESS`); các yêu cầu sau được xếp hàng; driver nhận từ nhiều process với thứ tự phát "global".
- Kiến trúc: thread phát nhạc tạo khi client đầu tiên mở handle (không tạo trong `DriverEntry` — do vấn đề session), tắt khi unload. `PlaybackState` giữ queue `LIST_ENTRY` (khóa `FastMutex` khởi tạo trong constructor), `PAGED_LOOKASIDE_LIST` cấp `FullNote` (= `Note` + `LIST_ENTRY`, ẩn với user-mode), semaphore đếm số note (max 1000), `KEVENT` stop event, handle thread.
- `DriverEntry`: cấp `PlaybackState` bằng `new` overload, tạo `\Device\KMelody` + symbolic link `\??\KMelody`, gán `DriverUnload` và các dispatch (CREATE/CLOSE chung một hàm).
- `MelodyDeviceControl` (`IOCTL_MELODY_PLAY`): kiểm tra `InputBufferLength % sizeof(Note) == 0`, `SystemBuffer` khác NULL, rồi `AddNotes`: mỗi note cấp từ lookaside, copy, `InsertTailList` dưới khóa; cuối cùng `KeReleaseSemaphore(&m_counter, 2, count, FALSE)` (2 là priority boost tùy chọn, 0 cũng được); debug bằng `KeReadStateSemaphore`.
- `MelodyCreateClose`: `IRP_MJ_CREATE` gọi `PlaybackState::Start(DeviceObject)` — dưới fast mutex, nếu `m_hThread` đã có thì trả success, ngược lại `IoCreateSystemThread` (ưu tiên hơn `PsCreateSystemThread` vì chống unload sớm) với hàm static `PlayMelody` và `this` làm context.
- Thread tạo trong `NtCurrentProcess()` chứ không phải System process: Beep phát theo session của caller, mà System process thuộc session 0 (không interactive) thì không có tiếng. Hệ lụy: process client đầu phải chứa thread suốt đời driver (không chết thật, vẫn thấy trong Task Manager), chỉ hỗ trợ một session; giải pháp tốt hơn là tạo thread trong Csrss.exe của session hiện tại (process critical, luôn tồn tại, protected từ Windows 8.1).
- `PlayMelody` static nhận `this` qua context rồi gọi instance method (cách khác: non-capturing lambda chuyển thành con trỏ hàm C). Thread lấy Beep device bằng `IoGetDeviceObjectPointer` (`DD_BEEP_DEVICE_NAME_U` từ `ntddbeep.h`), rồi vòng lặp `KeWaitForMultipleObjects` trên `{semaphore, stopEvent}`: `STATUS_WAIT_1` → stop signal → thoát; ngược lại `RemoveHeadList` dưới khóa (assert `link != &m_head` vì lấy list rỗng trả về head), lấy `FullNote` bằng `CONTAINING_RECORD`.
- Note tần số 0 = im lặng: delay bằng `KeDelayExecutionThread` (tương đương `Sleep`; interval âm, đơn vị 100ns — ms × −10000). Note thường: dựng IRP `IOCTL_BEEP_SET` (`BEEP_SET_PARAMETERS`) kèm `doneEvent`, gửi `IoCallDriver`; Beep luôn trả `STATUS_PENDING` nên chờ `doneEvent` (signal khi hoàn tất), delay `Duration`, delay `Delay` giữa các lần lặp nếu `Repeat > 1`. Cuối vòng trả note về lookaside; thoát thì `ObDereferenceObject(beepFileObject)`.
- `Stop`: `KeSetEvent(&m_stopEvent, 2, FALSE)` rồi minh họa chờ thread kết thúc: `ObReferenceObjectByHandle(m_hThread, SYNCHRONIZE, *PsThreadType, ...)` lấy thread object, `KeWaitForSingleObject`, `ObDereferenceObject`, `ZwClose(m_hThread)`. Việc chờ không bắt buộc với `IoCreateSystemThread` nhưng là kỹ thuật đáng nhớ.

#### Client Code
- Client: `CreateFile(MELODY_SYMLINK, GENERIC_WRITE, ...)`, nạp mảng `Note`, gọi `DeviceIoControl(hDevice, IOCTL_MELODY_PLAY, ...)` hai lần (lần hai có `Repeat`/`Delay`), rồi `CloseHandle`. Project: KMelody và Melody.
- Bài tập: thay `IoCreateSystemThread` bằng `PsCreateSystemThread`; chuyển sang lookaside API mới; tạo thread trong Csrss của session hiện tại (tìm bằng `ZwQuerySystemInformation`); đa session — một `PlaybackState` mỗi session (dùng `ZwQueryInformationProcess` với `ProcessSessionId` hoặc `PsGetCurrentProcessSessionId` undocumented).

### Invoking System Services
- System call từ user mode đi qua NtDll.dll tới executive; driver gọi được bản Nt hoặc Zw (Zw set previous mode = `KernelMode`). Một số được document (`ZwCreateFile`), nhiều cái không hoặc chỉ một phần.
- `NtQuerySystemInformation` không có trong WDK nhưng khai báo trong `Winternl.h` (macro cũ `IN`/`OUT` trước thời SAL); copy khai báo, đổi thành biến thể Zw. Giá trị `SYSTEM_INFORMATION_CLASS` và struct phần lớn reverse-engineer, có trong project Process Hacker (phnt); ít khi đổi vì công cụ của Microsoft cũng phụ thuộc.
- API chỉ có ở một số phiên bản Windows: tra động bằng `MmGetSystemRoutineAddress` — bản kernel của `GetProcAddress`.
- `NtQueryInformationProcess` (cũng trong `Winternl.h`): kernel headers có nhiều giá trị `PROCESSINFOCLASS` (`ProcessBasicInformation` = 0, `ProcessDebugPort` = 7, `ProcessWow64Information` = 26, `ProcessImageFileName` = 27, `ProcessBreakOnTermination` = 29; đầy hơn trong `ntddk.h`) nhưng không có prototype. Ví dụ: tên image process hiện tại qua `ZwQueryInformationProcess(NtCurrentProcess(), ProcessImageFileName, buffer, ...)` với buffer là `UNICODE_STRING`, rồi `ExFreePool`.

#### Example: Enumerating Processes
- EnumProc copy từ `Winternl.h`: `SystemProcessInformation` = 5, struct `SYSTEM_PROCESS_INFORMATION` (nhiều member `Reserved`; bản đầy trong Process Hacker) và extern khai báo `ZwQuerySystemInformation`.
- Mẹo 2 lần gọi: lần đầu buffer NULL, size 0 để lấy dung lượng cần ở tham số cuối, cộng 4KB dự phòng process mới; cấp `PagedPool` (tag `'cprP'`) rồi gọi lại với buffer thật.
- Duyệt bằng cách nhảy `NextEntryOffset` byte (0 = hết); in PID, Session, Handles, Threads, ImageName (`%wZ`) bằng `DbgPrint`, `ExFreePool`. `DriverEntry` gọi hàm enum rồi trả `STATUS_UNSUCCESSFUL` để driver unload ngay.

## API / cấu trúc / hằng số quan trọng

| Tên | Loại | Vai trò & ghi chú ngắn |
|---|---|---|
| `PsCreateSystemThread` / `IoCreateSystemThread` | hàm | Tạo system thread; bản Io giữ reference chống unload sớm (Win 8+) |
| `PsTerminateSystemThread` | hàm | Kết thúc thread — bắt buộc với `PsCreateSystemThread` |
| `ExAllocatePoolWithTagPriority` | hàm | Cấp phát có `EX_POOL_PRIORITY`, hỗ trợ special pool |
| `ExAllocatePool2` / `ExAllocatePool3` | hàm | Cấp phát mới (Win10 1909+): `POOL_FLAG_*`; bản 3 nhận `POOL_EXTENDED_PARAMETER` |
| `ExCreatePool` / `ExDestroyPool` / `ExFreePool2` | hàm | Tạo / hủy secure pool; giải phóng có hỗ trợ secure pool |
| `ExInitializePagedLookasideList` (+NPaged) | hàm | Init lookaside cổ điển; Depth để 0 |
| `ExAllocateFromPagedLookasideList` / `ExFreeToPagedLookasideList` / `ExDeletePagedLookasideList` | hàm | Cấp / trả block; Delete tự giải phóng mọi block còn lại |
| `ExInitializeLookasideListEx` + Allocate/Free/Delete tương ứng | hàm | Lookaside API mới; struct phải nằm trong non-paged memory |
| `IoBuildDeviceIoControlRequest` | hàm | Dựng IRP device control, điền sẵn stack location đầu |
| `IoCallDriver` | hàm | Gửi IRP tới device, gọi dispatch routine của driver đích |
| `IoGetDeviceObjectPointer` | hàm | Lấy `PDEVICE_OBJECT` theo tên; trả kèm `FILE_OBJECT` giữ reference |
| `KeDelayExecutionThread` | hàm | Delay kiểu `Sleep`; interval âm = tương đối, 100ns |
| `KeWaitForMultipleObjects` | hàm | Chờ nhiều object; `STATUS_WAIT_n` chỉ ra object được signal |
| `KeReleaseSemaphore` / `KeReadStateSemaphore` | hàm | Tăng đếm semaphore / đọc trạng thái debug |
| `ObReferenceObjectByHandle` / `ObDereferenceObject` | hàm | Lấy thread object từ handle để chờ; phải deref khi xong |
| `MmGetSystemRoutineAddress` | hàm | Tra động kernel routine — `GetProcAddress` bản kernel |
| `ZwQuerySystemInformation` / `ZwQueryInformationProcess` | hàm | System call undocumented, khai báo copy từ `Winternl.h` |
| `POOL_EXTENDED_PARAMETER`, `POOL_EXTENDED_PARAMS_SECURE_POOL` | struct | Tham số priority / secure pool cho `ExAllocatePool3` |
| `PAGED_LOOKASIDE_LIST`, `LOOKASIDE_LIST_EX` | struct | Opaque struct quản lý lookaside list |
| `Note`, `FullNote`, `PlaybackState` | struct | Kiểu dữ liệu của mẫu KMelody |
| `IOCTL_MELODY_PLAY`, `IOCTL_BEEP_SET`, `DD_BEEP_DEVICE_NAME_U` | hằng số/macro | Control code KMelody/Beep; tên `\Device\Beep` trong `ntddbeep.h` |

## Code / mẫu thiết kế đáng nhớ

Overload `new`/`delete` cho kernel — dùng cho mọi object C++ cấp phát động trong driver:

```cpp
void* __cdecl operator new(size_t size, POOL_TYPE pool, ULONG tag = DRIVER_TAG) {
    return ExAllocatePoolWithTag(pool, size, tag);
}
void* __cdecl operator new(size_t size, void* p) { return p; } // placement new
void  __cdecl operator delete(void* p, size_t) { ExFreePool(p); }
// usage: auto data = new (PagedPool) MyData(200);
```

Tạo playback thread đúng một lần khi client đầu mở handle, chống unload sớm:

```cpp
NTSTATUS PlaybackState::Start(PVOID IoObject) {
    Locker locker(m_lock);
    if (m_hThread) return STATUS_SUCCESS;
    return IoCreateSystemThread(IoObject, &m_hThread, THREAD_ALL_ACCESS,
        nullptr, NtCurrentProcess(), PlayMelody, this);
}
```

Gửi yêu cầu tới driver khác — pattern dựng IRP + gửi + chờ khi `STATUS_PENDING`:

```cpp
auto irp = IoBuildDeviceIoControlRequest(IOCTL_BEEP_SET, beepDevice,
    &params, sizeof(params), nullptr, 0, FALSE, &doneEvent, &ioStatus);
status = IoCallDriver(beepDevice, irp);
if (status == STATUS_PENDING)
    KeWaitForSingleObject(&doneEvent, Executive, KernelMode, FALSE, nullptr);
```

## Cạm bẫy & lưu ý

- `PsCreateSystemThread` bắt buộc gọi `PsTerminateSystemThread` để kết thúc thread; handle thread từ cả hai API phải đóng bằng `ZwClose`.
- Special pool tốn ít nhất một trang mỗi lần cấp — chỉ bật khi săn memory corruption; mọi lệnh cấp phát phải xử lý trả NULL.
- Không khai báo global object có constructor làm việc (không có runtime gọi nó); cách quanh: pointer toàn cục + `new` trong `DriverEntry`, `delete` trong unload.
- `LOOKASIDE_LIST_EX` phải nằm trong non-paged memory dù list quản lý pool gì; `RAISE_ON_FAIL` và `FAIL_NO_RAISE` loại trừ nhau, cờ sau cần custom allocator.
- `RemoveHeadList` trên list rỗng trả về chính head — cần assert (`NT_ASSERT(link != &m_head)`).
- Thread trong System process (session 0) thì Beep không có tiếng; thread trong process client thì process đó không chết thật và chỉ phục vụ một session — khắc phục bằng Csrss.exe của session hiện tại.
- Sau `ObReferenceObjectByHandle` bắt buộc `ObDereferenceObject`, nếu không thread object (và process của nó) sống mãi; interval âm của `KeDelayExecutionThread` tính theo 100ns (ms × −10000).
- API undocumented tuy ít đổi (công cụ của Microsoft cũng dùng) nhưng không có bảo đảm chính thức.

## Tóm lại cần nhớ

- Thao tác dài nên chạy trên thread riêng của driver; `IoCreateSystemThread` (Windows 8+) an toàn vì tự giữ reference chống unload sớm.
- Block cố định kích thước dùng lặp lại thì dùng lookaside list; API `Ex*LookasideListEx` mới thống nhất paged/non-paged và mang được context.
- Overload `new`/`delete` mang constructor/destructor và cú pháp C++ vào việc cấp phát pool trong kernel.
- Gọi driver khác: `IoGetDeviceObjectPointer` → `IoBuildDeviceIoControlRequest` → `IoCallDriver`, chờ event nếu `STATUS_PENDING`.
- System service undocumented gọi được bằng khai báo tự copy (ưu tiên Zw) và kiểm tra bằng `MmGetSystemRoutineAddress`.
- Còn nhiều kỹ thuật nữa ở chương 11; chương kế: process và thread notifications.
