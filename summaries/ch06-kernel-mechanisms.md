# Chương 6: Kernel Mechanisms

> Nguồn: *Windows Kernel Programming, 2nd Edition* — Pavel Yosifovich, trang 137–189

## Tổng quan

Chương trình bày các cơ chế mà Windows kernel cung cấp cho driver: IRQL, DPC, APC, SEH, system crash/bugcheck, các primitive đồng bộ hóa thread (Interlocked, dispatcher objects, fast mutex, semaphore, event, executive resource), đồng bộ hóa ở IRQL cao (spin lock) và work items. Đây là nền tảng để driver vừa chạy đúng, vừa tránh crash, vừa hiểu được những gì xảy ra khi debug hệ thống.

## Nội dung theo từng mục

### Interrupt Request Level (IRQL)
- Phần cứng báo hiệu cần chú ý bằng interrupt; mỗi interrupt gắn với một mức ưu tiên gọi là IRQL (do HAL quyết định, không trùng với đường vật lý IRQ). IRQL là thuộc tính của **mỗi processor**, coi nó như một register bình thường.
- Quy tắc cơ bản: CPU luôn chạy code có IRQL cao nhất. Khi interrupt đến, CPU lưu context vào kernel stack của thread đang chạy, nâng IRQL lên mức của interrupt rồi chạy ISR; interrupt bằng hoặc thấp hơn bị che (masked). ISR của mọi interrupt chạy trong context của **thread bị interrupt** — Windows không có thread riêng cho interrupt; và vì context switch không thể xảy ra khi IRQL ≥ 2, không thread nào "chèn" vào được. Thread bị interrupt không bị trừ quantum.
- User mode luôn chạy ở IRQL 0 (nên tài liệu user-mode không nhắc đến IRQL). Các mức quan trọng:
  - `PASSIVE_LEVEL` (0): mức "bình thường", scheduling hoạt động bình thường.
  - `APC_LEVEL` (1): dùng cho special kernel APC; scheduling vẫn bình thường.
  - `DISPATCH_LEVEL` (2): scheduler không thể hoạt động trên CPU này; **cấm truy cập paged memory** (crash) và **cấm wait lên kernel object** (crash), trừ wait với timeout = 0.
  - Device IRQL: dải cho hardware interrupt, 3–11 trên x64/ARM/ARM64, 3–26 trên x86; mọi ràng buộc của IRQL 2 vẫn áp dụng.
  - `HIGH_LEVEL`: cao nhất, che mọi interrupt (15 trên x64/ARM/ARM64, 31 trên x86), dùng trong vài API thao tác linked list.
- Debug: `!irql` xem IRQL hiện tại của CPU (có thể chỉ định số CPU), `!idt` xem các interrupt đã đăng ký trong IDT.

### Raising and Lowering IRQL
- Kernel mode có thể nâng IRQL bằng `KeRaiseIrql` và hạ bằng `KeLowerIrql`; mã lệnh chạy giữa hai lần gọi thực thi ở IRQL mới.
- Quy tắc an toàn: phải hạ IRQL **trong cùng hàm** đã nâng — tuyệt đối không trả về từ hàm với IRQL cao hơn lúc vào; `KeRaiseIrql` phải thực sự nâng và `KeLowerIrql` phải thực sự hạ, nếu không hệ thống sẽ crash.

### Thread Priorities vs. IRQLs
- IRQL là thuộc tính của processor, priority là thuộc tính của thread. Priority chỉ có ý nghĩa khi IRQL < 2; ở IRQL ≥ 2 thread có "quantum vô hạn" — chạy đến khi tự hạ IRQL xuống dưới 2.
- Ở IRQL ≥ 2 lâu là điều xấu (user mode chắc chắn không chạy). Task Manager thể hiện thời gian CPU ở IRQL ≥ 2 qua pseudo-process "System Interrupts"; Process Explorer gọi là "Interrupts".

### Deferred Procedure Calls
- Trong luồng I/O điển hình: ISR của thiết bị chạy ở Device IRQL khi hardware hoàn tất, nhưng ISR **không được gọi** `IoCompleteRequest` vì hàm này chỉ được gọi ở IRQL ≤ DISPATCH_LEVEL (2); gọi sẽ crash. Lý do của ràng buộc: `IoCompleteRequest` khá đắt — nếu gọi trong ISR, các interrupt khác sẽ bị che quá lâu.
- Giải pháp là DPC (Deferred Procedure Call): một object (`KDPC`, cấp phát từ non-paged pool) đóng gói một hàm sẽ chạy ở `DISPATCH_LEVEL`, nơi gọi `IoCompleteRequest` được phép. Driver khởi tạo trước bằng `KeInitializeDpc`; cuối ISR gọi `KeInsertQueueDpc` để xếp DPC chạy sớm nhất có thể.
- Mỗi CPU có queue DPC riêng; mặc định DPC xếp vào CPU hiện tại. Sau khi ISR trả về, trước khi IRQL kịp xuống 0, CPU hạ về IRQL 2 và xử lý queue theo FIFO cho đến khi cạn, rồi mới quay về code bị gián đoạn. DPC không quá cao để vẫn cho hardware interrupt khác vào phục vụ trên cùng CPU. Có thể tùy chỉnh qua `KeSetImportanceDpc` và `KeSetTargetProcessorDpc`.
- ISR không được tự hạ IRQL xuống 2 rồi gọi `IoCompleteRequest` — cách này có thể gây deadlock (lí do liên quan spin lock, xem phần sau).

### Using DPC with a Timer
- Kernel timer (`KTIMER`) cho phép hẹn giờ hết hạn theo khoảng tương đối hoặc thời điểm tuyệt đối; nó là dispatcher object (có thể wait), nhưng cách tiện hơn là gắn callback qua DPC.
- Quy trình: `KeInitializeTimer` + `KeInitializeDpc` với callback, rồi `KeSetTimer` với interval dạng `LARGE_INTEGER` theo đơn vị 100nsec, **giá trị âm** cho khoảng tương đối (millisecond × −10000). Khi hết hạn, DPC được xếp vào queue và callback chạy ở `DISPATCH_LEVEL` — mạnh hơn callback ở IRQL 0 vì chắc chắn chạy trước mọi user-mode code (và phần lớn kernel code).

### Asynchronous Procedure Calls
- DPC chạy trên bất kỳ thread nào; APC (Asynchronous Procedure Call) thì **nhắm vào một thread cụ thể** — mỗi thread có queue APC riêng, chỉ thread đó mới chạy được hàm trong APC.
- Ba loại APC:
  - User-mode APC: chạy trong user mode ở `PASSIVE_LEVEL`, chỉ khi thread vào **alertable state** (qua `SleepEx`, `WaitForSingleObjectEx`, `WaitForMultipleObjectsEx`… với tham số cuối TRUE).
  - Normal kernel-mode APC: chạy trong kernel ở `PASSIVE_LEVEL`, chiếm quyền trước user-mode code và user APC.
  - Special kernel APC: chạy ở `APC_LEVEL` (1), chiếm quyền trước tất cả; I/O manager dùng để hoàn tất I/O (chương sau).
- API APC ở kernel mode không được tài liệu hóa chính thức. User mode dùng APC qua `ReadFileEx`/`WriteFileEx` (I/O bất đồng bộ, completion là user APC) hoặc `QueueUserAPC`.

### Critical Regions and Guarded Regions
- Critical Region chặn user-mode APC và normal kernel APC (special kernel APC vẫn chạy vào được): vào bằng `KeEnterCriticalRegion`, ra bằng `KeLeaveCriticalRegion`. Một số API **yêu cầu** đang ở critical region, đặc biệt khi dùng executive resources.
- Guarded Region chặn **mọi** loại APC: `KeEnterGuardedRegion` / `KeLeaveGuardedRegion`; gọi enter đệ quy bao nhiêu lần thì phải gọi leave đúng bấy nhiêu lần.
- Nâng IRQL lên `APC_LEVEL` cũng vô hiệu hóa việc chuyển giao mọi APC. Sách khuyến nghị viết RAII wrapper cho enter/leave critical và guarded regions.

### Structured Exception Handling
- Exception là sự kiện **đồng bộ**, tái lập được (khác interrupt — bất đồng bộ): chia cho 0, breakpoint, page fault, stack overflow, lệnh không hợp lệ… Handler kernel được gọi qua IDT (cùng bảng với ISR); các vector số thấp chính là exception handler (`KiDivideErrorFault` 0, `KiBreakpointTrap` 3, `KiInvalidOpcodeFault` 6, `KiPageFault` 14…), xem được bằng `!idt`.
- Một số exception do kernel nêu ra sau fault của CPU: ví dụ page fault mà trang không tồn tại → Memory Manager ném Access Violation. Kernel tìm handler trong hàm gây exception, rồi lần ngược call stack; nếu cạn stack mà không có handler → crash.
- C được bổ sung 4 từ khóa: `__try` (khối có thể phát sinh exception), `__except` (quyết định và xử lý exception), `__finally` (code chạy **bất kể** thoát khối thế nào — bình thường, `return`, hay exception), `__leave` (nhảy tối ưu tới `__finally`). Chỉ có cặp `__try/__except` và `__try/__finally` là hợp lệ, nhưng có thể lồng tùy ý.

### Using __try/__except
- Không bao giờ tin buffer user-mode: user có thể free buffer ngay trước khi driver truy cập; không bảo vệ thì lỗi của user làm driver crash. Bọc truy cập buffer trong `__try/__except` (ví dụ IRP_MJ_WRITE handler với `Irp->UserBuffer`, `STATUS_ACCESS_VIOLATION` khi có exception).
- `EXCEPTION_EXECUTE_HANDLER` bắt mọi exception; có thể lọc bằng `GetExceptionCode()` và trả `EXCEPTION_CONTINUE_SEARCH` để kernel tiếp tục tìm handler ở trên call stack.
- Giới hạn: Access violation ở **user space** bắt được, nhưng ở **kernel space** thì không — vẫn crash (chuyện xấu đã xảy ra thì kernel không tha cho driver).
- Driver có thể chủ động ném exception bằng `ExRaiseStatus` (generic, ví dụ `ExRaiseAccessViolation`), hoặc chủ động crash hệ thống bằng `KeBugCheckEx(BugCheckCode, 4 tham số)` — nếu code là loại Microsoft tài liệu hóa thì 4 tham số phải theo đúng nghĩa tài liệu.

### Using __try/__finally
- `__try/__finally` không phải để xử lý exception mà để đảm bảo cleanup: code trong `__finally` chạy dù khối thoát bình thường, bằng `return`, hay do exception (tương tự `finally` trong Java/C#).
- Vấn đề của code thường: cấp phát rồi `return` sớm hoặc exception xảy ra giữa chừng → leak bộ nhớ; exception thì không thể xử lý bằng kỹ thuật coding thông thường. `__finally` giải quyết cả hai (ví dụ `ExAllocatePoolWithTag` / `ExFreePool`).
- Áp dụng được cho mọi loại acquire/release, ví dụ `ExAcquireFastMutex` / `ExReleaseFastMutex` trong `__try/__finally`.

### Using C++ RAII Instead of __try / __finally
- C++ không cần `finally` vì có destructor: class template `kunique_ptr` quản lý buffer từ pool, destructor gọi `ExFreePool` khi ra khỏi scope. Bản hoàn chỉnh xóa copy constructor/copy assignment (đơn owner), cho phép move constructor/move assignment (chuyển ownership, C++11+), cùng `operator bool`, `operator->`, `operator*`, `Release()`.
- Khuyết điểm lớn: nếu exception xảy ra thì **destructor không được gọi** (không có C++ runtime/unwinding trong kernel) → leak. Vẫn rất hữu dụng vì nhiều chỗ không kỳ vọng exception, và nếu có exception không ai xử lý thì hệ thống đáng lẽ cũng phải crash.

### System Crash
- Crash (BSOD / bugcheck / stop error) là **cơ chế bảo vệ**: kernel code đáng tin mà làm chuyện xấu thì dừng tất cả là an toàn nhất, tránh làm hỏng file/Registry dẫn đến hệ thống không boot được. Windows 10 có biến thể màu (xanh lá cho insider preview, tác giả từng gặp màu hồng). Nếu có kernel debugger gắn vào, debugger sẽ break để khảo sát trước.
- Cấu hình qua Startup and Recovery: ghi event log khi crash (mặc định, nên giữ), tự động restart (mặc định từ Windows 2000), và quan trọng nhất là loại dump file.
- Dump không được ghi trực tiếp ra file đích lúc crash mà ghi vào **page file đầu tiên**; khi restart kernel thấy dump trong page file rồi copy sang file đích (lúc crash, I/O system có thể chưa đủ ổn định để ghi file mới). Page file phải đủ lớn chứa dump. Dump chỉ chứa **physical memory**.
- Các loại dump:
  - Small memory dump (256 KB từ Windows 8, 64 KB trước đó): thông tin cơ bản + thread gây crash; thường quá ít để chẩn đoán.
  - Kernel memory dump (mặc định Windows 7 trở về trước): toàn bộ kernel memory, không có user memory — thường là đủ vì crash do kernel code gây ra.
  - Complete memory dump: toàn bộ physical memory kể cả trang chưa dùng, file có thể rất lớn.
  - Automatic memory dump (mặc định Windows 8+): giống kernel dump nhưng kernel tự điều chỉnh page file khi boot (nếu page file để "System managed") để đủ chứa kernel dump.
  - Active memory dump (Windows 10+): giống complete nhưng bỏ trang chưa dùng và bỏ memory của guest VM đang host.

### Crash Dump Information
- Mở dump trong WinDbg (File/Open Dump File); WinDbg gợi ý chạy `!analyze -v` — lệnh phân tích đầu tiên chuẩn nhất. Call stack sẽ dừng tại `KeBugCheckEx`.
- Ví dụ `DRIVER_IRQL_NOT_LESS_OR_EQUAL (0xd1)` với 4 đối số: Arg1 = memory referenced, Arg2 = IRQL (2), Arg3 = 0 đọc / 1 ghi, Arg4 = địa chỉ gây truy cập. Trong ví dụ, `!analyze -v` chỉ đúng driver `myfault.sys` vì crash "dễ" — thủ phạm nằm ngay trên stack.
- Crash khó: driver ghi tràn buffer làm hỏng memory của driver/kernel khác, rồi về sau kernel đọc dữ liệu hỏng và crash — thủ phạm không còn trên stack nào. Driver Verifier (module 12) giúp bắt loại lỗi này. Tra "Bugcheck Code Reference" trong tài liệu debugger để hiểu các bugcheck code phổ biến.

### Analyzing a Dump File
- Dump file là snapshot memory hệ thống, phân tích như một phiên kernel debugging nhưng **không đặt breakpoint được và không dùng lệnh go**; các lệnh `!process`, `!thread`, `lm`, `k` vẫn dùng bình thường.
- Mẹo hữu ích: prompt hiển thị CPU hiện tại, chuyển CPU bằng `~ns`; `!running` (với `-t`) liệt kê thread đang chạy trên mọi processor lúc crash kèm call stack; `!stacks` liệt kê mọi thread stack, có thể kèm chuỗi tìm kiếm (ví dụ `!stacks 0 myfault`) để định vị code driver trên stack của thread nào đó dù driver không phải thread đang chạy; địa chỉ ETHREAD bên cạnh dòng dùng được cho `!thread`.

### System Hang
- Hệ thống treo (không responsive) không tự sinh dump; cần chủ động tạo. Nếu còn responsive một phần: dùng Sysinternals NotMyFault để ép crash và sinh dump (chính công cụ tạo dump ví dụ trong sách); lưu ý chọn đúng bản 32/64-bit (tên file 64-bit có hậu tố "64") vì driver `myfault.sys` sẽ không load nếu sai.
- Nếu treo hoàn toàn nhưng gắn được kernel debugger: debug bình thường hoặc tạo dump bằng `.dump`. Nếu không gắn được debugger: cấu hình trước trong Registry để crash bằng tổ hợp phím bàn phím; crash code khi đó là 0xE2 (`MANUALLY_INITIATED_CRASH`).

### Thread Synchronization
- Nhiều thread cùng truy cập một vùng memory mà có ít nhất một writer → data race: mọi thứ mất kiểm soát, thường sớm muộn cũng crash, hỏng dữ liệu gần như chắc chắn. Ví dụ điển hình: driver dùng linked list nhận dữ liệu từ nhiều client; thao tác list phải nguyên tử. Kernel cung cấp nhiều primitive cho việc này.

### Interlocked Operations
- Họ hàm `Interlocked*` là **compiler intrinsics** — lệnh CPU ngụy trang thành hàm, nguyên tử nhờ phần cứng, không dùng software object, và có cả ở user mode. Nếu giải quyết được việc thì đây là lựa chọn hiệu quả nhất.
- Tăng/giảm một số nguyên tưởng chừng nguyên tử nhưng thực ra không: hai thread cùng tăng có thể làm mất phép tăng (kết quả 1 thay vì 2); caching và store buffer của CPU hiện đại còn làm tình trạng này dễ xảy ra hơn nữa.
- Table 6-2: `InterlockedIncrement`(/16/64), `InterlockedDecrement`(/16/64), `InterlockedAdd`(/64), `InterlockedExchange`(/8/16/64), `InterlockedCompareExchange`(/64/128) — họ CompareExchange là nền tảng của lock-free programming (ngoài phạm vi sách).

### Dispatcher Objects
- Dispatcher objects (waitable objects) có trạng thái signaled/non-signaled (ý nghĩa tùy loại); thread có thể wait đến khi signaled, trong lúc wait không tốn CPU (trạng thái Waiting). Hàm wait chính: `KeWaitForSingleObject` và `KeWaitForMultipleObjects`.
- Tham số chính: truyền **pointer tới object** chứ không phải handle (nếu có handle thì `ObReferenceObjectByHandle`); `WaitReason` thường là `Executive` (hoặc `UserRequest` nếu wait theo yêu cầu user); `WaitMode` thường `KernelMode`; `Alertable` thường FALSE (TRUE cho phép user-mode APC trong lúc wait); `Timeout` NULL = chờ vô hạn, đơn vị 100nsec, **âm = tương đối, dương = tuyệt đối** tính từ 1/1/1601 nửa đêm; với wait nhiều object: `WaitType` (`WaitAll`/`WaitAny`) và `WaitBlockArray` (chỉ cần cấp phát từ non-paged nếu số object > `THREAD_WAIT_OBJECTS` = 3, vì dưới ngưỡng đó kernel dùng mảng built-in của thread).
- Giá trị trả về: `STATUS_SUCCESS` (object signaled) hoặc `STATUS_TIMEOUT` — **cả hai đều qua được `NT_SUCCESS`**. Với `WaitAny`, trả `STATUS_WAIT_0` + index của object signaled trong mảng.
- Table 6-3 ý nghĩa signaled: Process/Thread đã terminate; Mutex đang free; Event đang set; Semaphore count > 0; Timer đã hết hạn; File — I/O bất đồng bộ đã hoàn tất. Tất cả object này cũng có ở user mode (wait bằng `WaitForSingleObject`/`WaitForMultipleObjects`).

### Mutex
- Mutex (tên gốc Mutant) là object kinh điển cho bài toán một thread duy nhất được truy cập tài nguyên chung. Mutex signaled khi đang free; sau khi wait thành công thread trở thành **owner** và mutex chuyển non-signaled.
- Ownership quan trọng: chỉ owner mới release được; owner có thể acquire đệ quy (thành công tự động) nhưng phải release đúng số lần đã acquire thì mutex mới free lại.
- API: cấp phát `KMUTEX` từ non-paged memory; `KeInitializeMutex` (tham số `Level` không dùng, cho 0; khởi tạo unowned) hoặc `KeInitializeMutant` (được đặt initial owner ngay); wait bằng `KeWaitXxx`; release bằng `KeReleaseMutex` — trả về trạng thái cũ (thường bỏ qua), tham số `Wait` là gợi ý tối ưu: khi TRUE, IRQL không được hạ sau khi release để wait tiếp theo hiệu quả hơn (vì `KeReleaseMutex` nâng IRQL lên `DISPATCH_LEVEL`).
- Nên bọc phần truy cập dữ liệu trong `__try/__finally` để chắc chắn release. Sách xây RAII wrapper: struct `Mutex` với `Lock()`/`Unlock()`, và template generic `Locker<TLock>` gọi `Lock()` trong constructor, `Unlock()` trong destructor; dùng scope hẹp để acquire muộn nhất, release sớm nhất. Từ C++17 viết `Locker locker(MyMutex);` được (Visual Studio mặc định C++14, phải đổi trong project properties).

### Abandoned Mutex
- Nếu owner thread chết, mutex thành abandoned: kernel chủ động release (không ai release được nữa) để tránh deadlock, thread tiếp theo acquire bình thường nhưng giá trị trả về của wait là `STATUS_ABANDONED` thay vì `STATUS_SUCCESS`. Driver nên log trường hợp này — thường là dấu hiệu của bug.

### Other Mutex Functions
- `KeReadStateMutex` trả trạng thái hiện tại (recursive count, 0 = unowned); `KeQueryOwnerMutant` (trong `<ntifs.h>`) trả owner dưới dạng `CLIENT_ID` (thread + process ID). Kết quả có thể stale ngay sau khi gọi vì thread khác có thể vừa acquire/release; chỉ dùng cho debug.

### Fast Mutex
- Fast mutex là thay thế nhanh hơn, **không phải dispatcher object**, có API riêng. Khác với mutex thường: không acquire đệ quy được (deadlock); khi acquire, IRQL được nâng lên `APC_LEVEL` (1) nên mọi APC bị chặn; chỉ wait được vô hạn, không có timeout.
- Nhờ hai đặc điểm đầu, nó nhanh hơn; hầu hết driver cần mutex dùng fast mutex trừ khi có lý do chính đáng phải dùng mutex thường.
- API: `FAST_MUTEX` từ non-paged memory + `ExInitializeFastMutex`; acquire `ExAcquireFastMutex` (hoặc `ExAcquireFastMutexUnsafe` nếu đã ở `APC_LEVEL`); release `ExReleaseFastMutex` / `ExReleaseFastMutexUnsafe`.
- **Không làm I/O khi đang giữ fast mutex**: I/O completion được chuyển giao bằng special kernel APC, mà APC đang bị chặn → deadlock.

### Semaphore
- Semaphore dùng để **giới hạn** cái gì đó (ví dụ độ dài queue). Khởi tạo bằng `KeInitializeSemaphore` với count khởi đầu và limit tối đa (`KSEMAPHORE` từ non-paged memory). Signal khi count > 0; mỗi wait thành công trừ count 1; count = 0 thì non-signaled. `KeReleaseSemaphore` cộng lại (`Adjustment` thường là 1; `Increment` là priority boost cho thread wait thành công, đa số driver để 1; `Wait` như ở mutex; trả về count cũ).
- Ví dụ sách: hàng đợi work items — thread thêm item phải lấy một count; thread xử lý xong item thì release để trả count, cho phép thread khác thêm tiếp.
- Semaphore với max = 1 **không** tương đương mutex: semaphore không có ownership — thread này acquire, thread khác release được; đó là đặc tính chủ đích, mục đích của nó khác mutex. `KeReadStateSemaphore` đọc count hiện tại.

### Event
- Event đóng gói một cờ boolean để đồng bộ luồng công việc: set event khi điều kiện xảy ra để giải phóng các thread đang chờ. `KEVENT` từ non-paged memory + `KeInitializeEvent` với loại và trạng thái ban đầu:
  - NotificationEvent (manual-reset): set thì giải phóng **mọi** thread đang chờ và giữ signaled cho đến khi reset tường minh.
  - SynchronizationEvent (auto-reset): set thì giải phóng **nhiều nhất một** thread rồi tự trở về non-signaled.
- API: `KeSetEvent` (set, có `Increment`/`Wait` như semaphore), `KeResetEvent` (reset, trả trạng thái cũ), `KeClearEvent` (reset, nhanh hơn vì không trả trạng thái cũ), `KeReadStateEvent` đọc trạng thái hiện tại.

### Named Events (khung thông tin)
- Event (cả mutex, semaphore) có thể đặt tên để chia sẻ với driver khác hoặc user-mode client. Tạo/mở theo tên: `IoCreateSynchronizationEvent` / `IoCreateNotificationEvent` — tạo event nếu chưa có (và set signaled) hoặc trả thêm handle nếu đã có; tên là full path trong Object Manager namespace (xem bằng WinObj). Hàm trả pointer tới event và một **kernel handle** qua `EventHandle`; trả NULL nếu thất bại. Nhớ `ZwClose` handle (hoặc `ObReferenceObject` pointer rồi đóng handle ngay, dùng xong `ObDereferenceObject`).

### Built-in Named Kernel Events (khung thông tin)
- Kernel cung cấp sẵn các notification event trong thư mục `\KernelObjects` báo trạng thái memory, driver có thể wait để nhận gợi ý cấp phát/thả memory: `HighMemoryCondition`, `LowMemoryCondition`, `HighPagedPoolCondition`/`LowPagedPoolCondition`, `HighNonPagedPoolCondition`/`LowNonPagedPoolCondition`, `HighCommitCondition`, `LowCommitCondition`, `MaximumCommitCondition` (gần hết memory và không tăng page file được nữa). Ví dụ: mở `\\KernelObjects\\LowCommitCondition` bằng `IoCreateNotificationEvent`, wait trên driver thread, thả memory khi được signal, rồi `ZwClose`.

### Executive Resource
- Mutex là khóa "bi quan": luôn chỉ cho 1 thread. Với dữ liệu đọc nhiều ghi ít, dùng primitive single-writer/multiple-readers: thread khai báo ý định read hoặc write; nhiều reader chạy đồng thời được, writer là exclusive. Executive Resource (`ERESOURCE` từ non-paged pool) không phải dispatcher object.
- API: `ExInitializeResourceLite` khởi tạo; `ExAcquireResourceExclusiveLite` (ghi) hoặc `ExAcquireResourceSharedLite` (đọc); release chung một hàm `ExReleaseResourceLite`.
- Ràng buộc: normal kernel APCs phải bị vô hiệu khi dùng — `KeEnterCriticalRegion` trước acquire, `KeLeaveCriticalRegion` sau release; có sẵn hàm gộp: `ExEnterCriticalRegionAndAcquireResourceExclusive`, `ExEnterCriticalRegionAndAcquireResourceShared`, và `ExReleaseResourceAndLeaveCriticalRegion`.
- Trước khi free memory chứa resource phải gọi `ExDeleteResourceLite`; đếm số waiter bằng `ExGetExclusiveWaiterCount` / `ExGetSharedWaiterCount`. Sách giao bài viết RAII wrapper cho executive resources.

### High IRQL Synchronization
- Các primitive trên dựa vào wait — nhưng code ở IRQL ≥ `DISPATCH_LEVEL` **không được wait**. Tình huống: timer DPC (IRQL 2) và `IRP_MJ_DEVICE_CONTROL` (IRQL 0) cùng truy cập linked list chung phải đồng bộ mà không wait được.
- Nếu hệ thống 1 CPU: chỉ cần code IRQL 0 tự nâng IRQL lên 2 khi truy cập dữ liệu chung — DPC không thể xen vào cùng CPU; xong thì hạ về 0.
- Nếu nhiều CPU: IRQL là thuộc tính từng CPU, DPC có thể chạy trên CPU khác (IRQL 0) → vẫn data race. Cần thứ như mutex nhưng đồng bộ giữa **processors** thay vì thread (thread vô nghĩa ở IRQL ≥ 2 vì scheduler không hoạt động): đó là Spin Lock.

### The Spin Lock
- Spin lock chỉ là một bit trong memory dùng với thao tác test-and-set nguyên tử qua API. CPU muốn acquire mà lock bị giữ sẽ **spin** (busy-wait) — không thể chuyển thread sang trạng thái Waiting ở IRQL ≥ 2.
- Quy trình acquire luôn 2 bước: nâng IRQL lên mức cao nhất trong số các hàm cần đồng bộ (ví dụ 2), rồi acquire spin lock; xong việc thì release và hạ IRQL (trừ khi đang trong DPC). Khởi tạo: `KSPIN_LOCK` từ non-paged pool + `KeInitializeSpinLock`.
- Table 6-4 — API theo IRQL:
  - `DISPATCH_LEVEL` (2): `KeAcquireSpinLock` / `KeReleaseSpinLock` (nâng/hạ IRQL đầy đủ).
  - `DISPATCH_LEVEL` (2): `KeAcquireSpinLockAtDpcLevel` / `KeReleaseSpinLockFromDpcLevel` — chỉ dùng khi đã ở IRQL 2 (điển hình là trong DPC), tối ưu vì không đổi IRQL.
  - Device IRQL: `KeAcquireInterruptSpinLock` / `KeReleaseInterruptSpinLock` — dùng spin lock bên trong `KINTERRUPT` để đồng bộ ISR với các hàm khác; driver có hardware interrupt dùng cặp này.
  - Device IRQL: `KeSynchronizeExecution` — acquire interrupt spin lock, gọi callback, rồi release; tương đương cặp trên.
  - `HIGH_LEVEL`: họ `ExInterlockedXxx` — thao tác linked list dựa trên `LIST_ENTRY`, dùng spin lock cung cấp và nâng IRQL lên HIGH_LEVEL; vì nâng IRQL luôn an toàn nên dùng được ở mọi IRQL.
- Quy tắc: release spin lock trong cùng hàm đã acquire, nếu không sẽ deadlock hoặc crash. Nguồn spin lock: driver tự cấp phát, hoặc sẵn trong object khác (KINTERRUPT), hoặc hệ thống-wide như **Cancel spin lock** — kernel acquire trước khi gọi cancellation routine của driver; đây là trường hợp duy nhất driver release một spin lock mình không acquire.

### Queued Spin Locks
- Biến thể của spin lock: luôn nâng lên `DISPATCH_LEVEL` (nên không dùng để đồng bộ với ISR được), và các CPU chờ theo **FIFO** — hiệu quả hơn khi contention cao (spin lock thường không đảm bảo thứ tự acquire).
- Khởi tạo như spin lock thường; acquire/release bằng `KeAcquireInStackQueuedSpinLock` / `KeReleaseInStackQueuedSpinLock`, caller cung cấp `KLOCK_QUEUE_HANDLE` (opaque) do hàm acquire điền và phải truyền đúng cái đó khi release. Nếu đã ở IRQL 2: `KeAcquireInStackQueuedSpinLockAtDpcLevel` / `KeReleaseInStackQueuedSpinLockFromDpcLevel`.

### Work Items
- Khi cần chạy code trên thread khác: với tác vụ nền dài hạn, tạo thread bằng `PsCreateSystemThread` / `IoCreateSystemThread` (Windows 8+; `IoCreateSystemThread` được ưu tiên vì gắn device/driver object vào thread, tăng reference nên driver không bị unload sớm); thread phải tự kết thúc bằng `PsTerminateSystemThread` (chi tiết ở chương 8). Với tác vụ có hạn thời gian, dùng **thread pool** của kernel qua work items.
- Work item là hàm xếp vào system thread pool; luôn chạy ở `PASSIVE_LEVEL` (0) — khác biệt chính so với DPC, nên DPC có thể queue work item để làm những việc cấm ở IRQL 2 (như I/O).
- Tạo work item theo 1 trong 2 cách: `IoAllocateWorkItem` (trả pointer tới `IO_WORKITEM` opaque, xong thì `IoFreeWorkItem`), hoặc cấp phát `IO_WORKITEM` với kích thước từ `IoSizeofWorkItem` + `IoInitializeWorkItem` (xong thì `IoUninitializeWorkItem`). Các hàm nhận device object, nên driver không được unload khi còn work item đang chờ hoặc đang chạy. Nhóm API `Ex…` (như `ExQueueWorkItem`) bị đánh dấu deprecated vì không gắn work item với driver — có thể unload khi work item còn chạy; luôn ưu tiên hàm `Io…`.
- Queue bằng `IoQueueWorkItem(IoWorkItem, WorkerRoutine, QueueType, Context)`; callback có prototype `(PDEVICE_OBJECT, PVOID Context)`. Có thêm `IoQueueWorkItemEx` — callback nhận thêm chính work item, tiện khi callback cần tự free work item trước khi thoát.
- `WORK_QUEUE_TYPE` gồm các mức priority: `CriticalWorkQueue` (13), `DelayedWorkQueue` (12), `HyperCriticalWorkQueue` (15), `NormalWorkQueue` (8), `BackgroundWorkQueue` (7), `RealTimeWorkQueue` (18), `SuperCriticalWorkQueue` (14), `MaximumWorkQueue`, `CustomPriorityWorkQueue` = 32. Tài liệu yêu cầu dùng `DelayedWorkQueue` nhưng thực tế các mức khác vẫn hoạt động.

## API / cấu trúc / hằng số quan trọng

| Tên | Loại | Vai trò & ghi chú ngắn |
|---|---|---|
| `PASSIVE_LEVEL` / `APC_LEVEL` / `DISPATCH_LEVEL` / `HIGH_LEVEL` | hằng số | IRQL 0 / 1 / 2 / cao nhất (15 x64, 31 x86); từ IRQL 2 trở lên: cấm paged memory và cấm wait |
| Device IRQL | hằng số | dải 3–11 (x64/ARM/ARM64) hoặc 3–26 (x86) cho hardware interrupt |
| `KeRaiseIrql` / `KeLowerIrql` | hàm | nâng/hạ IRQL của CPU hiện tại; phải hạ lại trong cùng hàm |
| `KeGetCurrentIrql` | hàm | đọc IRQL hiện tại (dùng kèm `NT_ASSERT`) |
| `!irql` / `!idt` | lệnh debugger | xem IRQL của CPU / các entry IDT (interrupt + exception handler) |
| `KDPC` / `KTIMER` | struct | DPC object và kernel timer (dispatcher object), cấp phát từ non-paged pool |
| `KeInitializeDpc` / `KeInsertQueueDpc` | hàm | khởi tạo DPC với callback / xếp DPC vào queue của CPU (mặc định CPU hiện tại) |
| `KeInitializeTimer` / `KeSetTimer` | hàm | khởi tạo timer / hẹn giờ; interval 100nsec, âm = tương đối |
| `KeEnterCriticalRegion` / `KeLeaveCriticalRegion` | hàm | chặn user + normal kernel APC (special kernel APC vẫn vào) |
| `KeEnterGuardedRegion` / `KeLeaveGuardedRegion` | hàm | chặn mọi APC; enter/leave phải khớp số lần đệ quy |
| `__try` / `__except` / `__finally` / `__leave` | từ khóa SEH | khối bắt exception / quyết định xử lý / cleanup chắc chắn chạy / nhảy tới finally |
| `EXCEPTION_EXECUTE_HANDLER` / `EXCEPTION_CONTINUE_SEARCH` | hằng số | xử lý exception tại chỗ / đẩy lên call stack |
| `GetExceptionCode` | hàm | lấy mã exception để lọc trong `__except` |
| `ExRaiseStatus` / `ExRaiseAccessViolation` | hàm | chủ động ném exception từ driver |
| `KeBugCheckEx` | hàm | chủ động crash hệ thống với bugcheck code + 4 tham số |
| `InterlockedIncrement/Decrement/Add/Exchange/CompareExchange` (các biến thể 8/16/32/64/128) | macro/intrinsic | thao tác nguyên tử bằng lệnh CPU; nền tảng lock-free |
| `KeWaitForSingleObject` / `KeWaitForMultipleObjects` | hàm | wait lên dispatcher object; Timeout 100nsec (âm tương đối/dương tuyệt đối), NULL = vô hạn |
| `THREAD_WAIT_OBJECTS` | hằng số | 3 — số object wait tối đa dùng mảng built-in của thread |
| `KMUTEX` / `KeInitializeMutex` / `KeInitializeMutant` / `KeReleaseMutex` | struct/hàm | mutex (Mutant) có ownership, acquire đệ quy được; release nâng IRQL lên 2 |
| `KeReadStateMutex` / `KeQueryOwnerMutant` | hàm | đọc trạng thái (recursive count) / owner (`CLIENT_ID`) — chỉ để debug, có thể stale |
| `FAST_MUTEX` / `ExInitializeFastMutex` / `ExAcquireFastMutex` / `ExReleaseFastMutex` (Unsafe) | struct/hàm | fast mutex: không đệ quy, nâng IRQL lên APC_LEVEL, chỉ wait vô hạn |
| `KSEMAPHORE` / `KeInitializeSemaphore` / `KeReleaseSemaphore` | struct/hàm | giới hạn count; không có ownership; `Increment` thường 1 |
| `KEVENT` / `KeInitializeEvent` / `KeSetEvent` / `KeResetEvent` / `KeClearEvent` / `KeReadStateEvent` | struct/hàm | event: `NotificationEvent` (manual-reset) hoặc `SynchronizationEvent` (auto-reset) |
| `IoCreateSynchronizationEvent` / `IoCreateNotificationEvent` | hàm | tạo/mở event theo tên trong Object Manager namespace; trả pointer + kernel handle |
| `ERESOURCE` / `ExInitializeResourceLite` / `ExAcquireResourceExclusiveLite` / `ExAcquireResourceSharedLite` / `ExReleaseResourceLite` / `ExDeleteResourceLite` | struct/hàm | single-writer/multiple-readers; yêu cầu critical region quanh acquire/release |
| `ExEnterCriticalRegionAndAcquireResourceExclusive/Shared`, `ExReleaseResourceAndLeaveCriticalRegion` | hàm | gộp critical region + acquire/release ERESOURCE |
| `ExGetExclusiveWaiterCount` / `ExGetSharedWaiterCount` | hàm | đếm waiter exclusive/shared của ERESOURCE |
| `KSPIN_LOCK` / `KeInitializeSpinLock` / `KeAcquireSpinLock` / `KeReleaseSpinLock` | struct/hàm | spin lock ở DISPATCH_LEVEL; busy-wait, không wait được |
| `KeAcquireSpinLockAtDpcLevel` / `KeReleaseSpinLockFromDpcLevel` | hàm | variant khi đã ở IRQL 2 (typical trong DPC), không đổi IRQL |
| `KeAcquireInterruptSpinLock` / `KeReleaseInterruptSpinLock` / `KeSynchronizeExecution` | hàm | spin lock trong `KINTERRUPT` để đồng bộ ISR với code khác |
| `ExInterlockedXxx` | hàm | thao tác linked list (`LIST_ENTRY`) nguyên tử ở HIGH_LEVEL, dùng được ở mọi IRQL |
| `KeAcquireInStackQueuedSpinLock` / `KeReleaseInStackQueuedSpinLock` | hàm | queued spin lock: FIFO cho CPU, luôn DISPATCH_LEVEL; dùng `KLOCK_QUEUE_HANDLE` |
| `IO_WORKITEM` / `IoAllocateWorkItem` / `IoFreeWorkItem` / `IoSizeofWorkItem` / `IoInitializeWorkItem` / `IoUninitializeWorkItem` | struct/hàm | tạo/quản lý work item gắn với device object |
| `IoQueueWorkItem` / `IoQueueWorkItemEx` | hàm | xếp work item vào thread pool; Ex-version callback nhận thêm work item |
| `WORK_QUEUE_TYPE` | enum | priority queue của thread pool: `DelayedWorkQueue` (12, khuyến nghị), `CriticalWorkQueue` (13), `HyperCriticalWorkQueue` (15), `NormalWorkQueue` (8), `RealTimeWorkQueue` (18), `CustomPriorityWorkQueue` = 32… |
| `PsCreateSystemThread` / `IoCreateSystemThread` / `PsTerminateSystemThread` | hàm | tạo thread hệ thống (Io bản 8+, ưu tiên hơn) / tự kết thúc thread |
| `STATUS_SUCCESS` / `STATUS_TIMEOUT` / `STATUS_WAIT_0` / `STATUS_ABANDONED` | hằng số | kết quả wait: signaled / hết giờ / index object signaled / mutex bị bỏ do owner chết |
| DRIVER_IRQL_NOT_LESS_OR_EQUAL (0xd1) | bugcheck code | truy cập địa chỉ không hợp lệ ở IRQL cao; Arg1 địa chỉ, Arg2 IRQL, Arg3 đọc/ghi, Arg4 địa chỉ code |
| `!analyze -v` / `!running` / `!stacks` | lệnh debugger | phân tích dump / thread đang chạy trên mọi CPU (-t kèm stack) / mọi thread stack, lọc theo chuỗi |

## Code / mẫu thiết kế đáng nhớ

Nâng và hạ IRQL đúng cách — mọi thao tác ở IRQL cao nên theo khuôn này (nâng, làm việc, hạ trong cùng hàm):

```cpp
// assuming current IRQL <= DISPATCH_LEVEL
KIRQL oldIrql; // typedefed as UCHAR
KeRaiseIrql(DISPATCH_LEVEL, &oldIrql);
NT_ASSERT(KeGetCurrentIrql() == DISPATCH_LEVEL);
// do work at IRQL DISPATCH_LEVEL
KeLowerIrql(oldIrql);
```

RAII cho synchronization primitive: wrapper `Mutex` với `Lock`/`Unlock` cộng template `Locker` dùng cho mọi loại lock có cùng giao diện (mutex, fast mutex, spin lock…); từ C++17 được viết `Locker locker(MyMutex);`:

```cpp
struct Mutex {
    void Init()  { KeInitializeMutex(&_mutex, 0); }
    void Lock()   { KeWaitForSingleObject(&_mutex, Executive, KernelMode, FALSE, nullptr); }
    void Unlock() { KeReleaseMutex(&_mutex, FALSE); }
private:
    KMUTEX _mutex;
};
template<typename TLock>
struct Locker {
    explicit Locker(TLock& lock) : _lock(lock) { lock.Lock(); }
    ~Locker() { _lock.Unlock(); }
private:
    TLock& _lock;
};
```

Timer + DPC: hẹn giờ callback chạy ở `DISPATCH_LEVEL`, interval âm theo 100nsec (msec × −10000):

```cpp
KTIMER Timer; KDPC TimerDpc;
void InitializeAndStartTimer(ULONG msec) {
    KeInitializeTimer(&Timer);
    KeInitializeDpc(&TimerDpc, OnTimerExpired, nullptr);
    LARGE_INTEGER interval;
    interval.QuadPart = -10000LL * msec;
    KeSetTimer(&Timer, interval, &TimerDpc);
}
void OnTimerExpired(KDPC* Dpc, PVOID context, PVOID, PVOID) {
    NT_ASSERT(KeGetCurrentIrql() == DISPATCH_LEVEL);
    // handle timer expiration
}
```

## Cạm bẫy & lưu ý

- Ở IRQL ≥ 2 (`DISPATCH_LEVEL`, Device IRQL, `HIGH_LEVEL`): truy cập paged memory / user buffer gây crash; wait lên kernel object gây crash (trừ timeout = 0); scheduler không chạy nên không có context switch.
- Nâng IRQL mà không hạ trong cùng hàm, hoặc `KeLowerIrql` không hạ đúng — crash. Tương tự, spin lock phải release trong cùng hàm đã acquire.
- ISR không được gọi `IoCompleteRequest` (chỉ được phép ở IRQL ≤ 2) và không được tự hạ IRQL để gọi — có thể deadlock; dùng DPC thay thế.
- Fast mutex: không acquire đệ quy (deadlock ngay); không làm I/O khi đang giữ vì I/O completion cần special kernel APC mà APC bị chặn ở `APC_LEVEL` → deadlock.
- ERESOURCE bắt buộc tắt normal kernel APC (critical region) quanh acquire/release; quên là lỗi.
- `__finally` và RAII khác nhau ở điểm mấu chốt: nếu exception xảy ra, destructor C++ **không được gọi** trong kernel (không có C++ runtime unwinding) → leak; `__finally` thì vẫn chạy.
- Access violation vào kernel space không thể catch bằng SEH — bắt buộc crash; chỉ exception ở user space mới bắt được. Không bao giờ tin buffer user-mode: luôn bọc truy cập trong `__try/__except`.
- Wait trả `STATUS_TIMEOUT` vẫn thỏa `NT_SUCCESS` — đừng lầm tưởng `NT_SUCCESS` nghĩa là wait thành công. `STATUS_ABANDONED` (mutex owner chết) nên được log vì thường là bug.
- `KeReadStateMutex`/`KeQueryOwnerMutant`/`KeReadStateSemaphore`/`KeReadStateEvent` trả thông tin có thể stale ngay sau khi gọi — chỉ dùng để debug.
- Dump file chỉ chứa physical memory và được ghi gián tiếp qua page file đầu tiên; page file phải đủ lớn. Khi phân tích dump: không đặt breakpoint, không lệnh go. Thủ phạm crash có thể không nằm trên stack nào (hỏng memory của người khác từ trước) — dùng Driver Verifier.
- Nhóm `ExQueueWorkItem` deprecated (không gắn với driver, nguy cơ unload khi đang chạy); dùng `IoAllocateWorkItem`/`IoQueueWorkItem` và đừng unload driver khi còn work item pending.
- Chương trình dạng DPC không được gọi bất kỳ hàm wait nào — đó là lý do sinh ra spin lock và work items cho code IRQL cao.

## Tóm lại cần nhớ

- IRQL là thuộc tính processor, quyết định code nào được chạy và được phép làm gì: từ IRQL 2 trở lên không paged memory, không wait, không context switch; mọi ISR chạy trong context thread bị interrupt.
- DPC là cầu nối đưa công việc từ Device IRQL xuống `DISPATCH_LEVEL` (complete IRP, timer callback); APC gắn với thread cụ thể với 3 mức (user, normal kernel, special kernel) và bị chặn bởi critical/guarded region hoặc IRQL APC_LEVEL.
- SEH (`__try/__except` để bắt exception — chỉ hiệu quả với user space; `__try/__finally` để cleanup chắc chắn) và RAII wrapper là công cụ chống leak/chống crash cơ bản của driver.
- Bugcheck là cơ chế bảo vệ, không phải hình phạt; biết cấu hình và phân tích crash dump (`!analyze -v`, `!running`, `!stacks`) là kỹ năng bắt buộc của người viết driver.
- Chọn primitive theo hoàn cảnh: Interlocked cho thao tác nguyên tử đơn giản; mutex/fast mutex cho khóa độc quyền (fast mutex mặc định nhưng cấm đệ quy và cấm I/O khi giữ); semaphore để giới hạn; event để báo tín hiệu; ERESOURCE cho đọc nhiều/ghi ít; spin lock (+queued) cho đồng bộ ở IRQL ≥ 2 giữa các CPU; work item để hạ công việc từ IRQL 2 về `PASSIVE_LEVEL`.
