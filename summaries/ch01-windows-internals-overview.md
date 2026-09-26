# Chương 1: Windows Internals Overview

> Nguồn: *Windows Kernel Programming, 2nd Edition* — Pavel Yosifovich, trang 9–27

## Tổng quan

Chương giới thiệu các khái niệm nền tảng của Windows internals: processes, virtual memory, threads, system calls, kiến trúc tổng thể và cơ chế handles/objects. Đây là nền móng cho mọi driver và cả code user-mode mức thấp, nên phải nắm vững trước khi viết driver.

## Nội dung theo từng mục

### Processes
- Process là đối tượng chứa và quản lý một thể hiện đang chạy của chương trình; nói "process runs" là sai — process quản lý, thread mới là thực thể thực thi code.
- Process sở hữu: image thực thi chứa code/data ban đầu (vài process đặc biệt do kernel tạo trực tiếp không có image), một private virtual address space, access token (primary token) lưu security context mà thread dùng trừ khi impersonation, handle table riêng cho executive objects (events, semaphores, files), và một hoặc nhiều thread.
- Process user-mode được tạo với một thread chạy `main`/`WinMain`; process không thread gần như vô dụng và bị kernel hủy.
- Định danh duy nhất là Process ID, chỉ unique khi kernel process object còn tồn tại (ID có thể tái dùng); file thực thi không phải định danh — năm instance notepad.exe là năm process riêng biệt dùng chung một image.

### Virtual Memory
- Mỗi process có address space riêng, private, linear; ban đầu gần rỗng (executable image và NtDll.Dll được map đầu, rồi subsystem DLL); process khác không truy cập trực tiếp được.
- Dải địa chỉ từ 0 (64KB đầu và cuối không thể commit) đến mức tối đa tùy bitness: 32-bit trên 32-bit Windows là 2 GB, lên tối đa 3 GB khi bật increase user virtual address space và PE có flag `LARGEADDRESSAWARE` (2 GB chỉ cần 31 bit nên bit 31/MSB dành cho app); process 64-bit có 8 TB (Windows 8 trở về trước) hoặc 128 TB (Windows 8.1 trở đi); process 32-bit trên 64-bit Windows có 4 GB nếu có `LARGEADDRESSAWARE`, không thì 2 GB.
- Địa chỉ process là relative, không absolute: muốn biết 0x20000 chứa gì phải biết nó thuộc process nào.
- "Virtual" nghĩa là địa chỉ không gắn với vị trí vật lý: CPU dịch virtual-to-physical khi truy cập; nếu trang không resident, CPU raise page fault, page fault handler của memory manager nạp dữ liệu từ file vào RAM, sửa page table entries rồi bảo CPU thử lại.
- Đơn vị quản lý là page, mọi thuộc tính (protection, state) theo page granularity; page thường (small) là 4 KB trên mọi kiến trúc được hỗ trợ.
- Large pages: 2 MB (x86/x64/ARM64) hoặc 4 MB (ARM), map qua Page Directory Entry không cần page table — dịch nhanh hơn và tận dụng TLB (cache bản dịch của CPU) tốt hơn; nhược điểm: cần RAM contiguous (có thể thất bại), luôn non-pageable, chỉ có protection đọc/ghi. Huge pages 1 GB (Windows 10/Server 2016+) được dùng tự động khi allocation ≥ 1 GB và tìm được vùng contiguous.

### Page States
- Free: chưa cấp phát; truy cập gây access violation; phần lớn page của process mới là free.
- Committed: đã cấp phát, truy cập được nếu không xung đột protection (ghi trang read-only vẫn gây access violation); map tới RAM hoặc file như page file.
- Reserved: dải địa chỉ giữ cho commit tương lai; với CPU giống Free (truy cập gây access violation), nhưng `VirtualAlloc`/`NtAllocateVirtualMemory` không chỉ định địa chỉ sẽ không cấp phát đè vào vùng reserved.

### System Memory
- Phần thấp address space dành cho user mode; OS nằm phần trên: 32-bit thường → upper 2 GB (0x80000000–0xFFFFFFFF); cấu hình 3 GB user space → OS còn 1 GB (0xC0000000–0xFFFFFFFF), chịu thiệt nhất là file system cache; 64-bit Windows 8/Server 2012 trở về trước → upper 8 TB; Windows 8.1/Server 2012 R2 trở đi → upper 128 TB.
- System space không phụ thuộc process — cùng kernel, cùng drivers phục vụ mọi process — nên địa chỉ ở đó là absolute; user mode truy cập vào system space gây access violation.
- System space chứa kernel, HAL và kernel drivers sau khi load: driver được bảo vệ khỏi user mode nhưng có tác động toàn hệ thống — driver leak bộ nhớ thì không được giải phóng kể cả sau khi unload, còn process user-mode chết thì kernel đóng mọi handle và giải phóng toàn bộ private memory.

### Threads
- Thread là thực thể thực sự thực thi code, nằm trong process và dùng tài nguyên process (virtual memory, handles tới kernel objects).
- Thread sở hữu: current access mode (user hoặc kernel), execution context (registers, execution state), một hoặc hai stacks, TLS array (Thread Local Storage), base priority và current (dynamic) priority, và processor affinity.
- Ba trạng thái phổ biến: Running (đang chạy trên một logical processor), Ready (chờ schedule vì processor bận), Waiting (chờ event; event xảy ra thì chuyển Ready); thêm trạng thái Deferred Ready — anh em của Ready — để giảm internal locking.

### Thread Stacks
- Mỗi thread có ít nhất một stack trong kernel space, rất nhỏ: mặc định 12 KB (32-bit) hoặc 24 KB (64-bit); kernel stack luôn resident trong RAM khi thread đang Running hoặc Ready.
- Thread user-mode có stack thứ hai trong user space, lớn hơn nhiều (mặc định tới 1 MB) và có thể bị page out.
- User stack lớn dần theo nhu cầu: một lượng committed nhỏ ban đầu (có thể 1 page), page kế tiếp đặt `PAGE_GUARD`, phần còn lại reserved; khi chạm guard page → page-guard exception → memory manager bỏ guard, commit thêm page và đặt `PAGE_GUARD` cho page kế; thực tế Windows dùng 3 guard pages.
- Kích thước stack lấy mặc định từ PE header (luôn dùng cho thread đầu tiên); `CreateThread`/`CreateRemoteThread(Ex)` chỉ truyền được một giá trị (commit hoặc reserve, tùy flag), 0 dùng mặc định; `NtCreateThreadEx` cho chỉ định cả hai.

### System Services (a.k.a. System Calls)
- Các thao tác không thuần tính toán (cấp phát bộ nhớ, mở file, tạo thread...) chỉ code kernel mode làm được, nên cần cơ chế chuyển sang kernel mode.
- Ví dụ File/Open của Notepad: gọi `CreateFile` (kernel32.dll, vẫn user mode) → gọi `NtCreateFile` (NTDLL.dll — Native API, tầng thấp nhất còn ở user mode, được document trong WDK) → đặt system service number vào EAX → phát lệnh `syscall` (x64) hoặc `sysenter` (x86) → chuyển kernel mode, nhảy tới system service dispatcher.
- Dispatcher lấy EAX làm index vào System Service Dispatch Table (SSDT) để nhảy tới system service thật — `NtCreateFile` do I/O manager cài đặt, cùng tên và tham số với bản NTDLL; xong service, thread về user mode chạy lệnh kế sau `syscall`/`sysenter`.

### General System Architecture
- User processes: process bình thường chạy từ image (Notepad.exe, cmd.exe, explorer.exe...).
- Subsystem DLLs: hiện thực API của một subsystem — một "góc nhìn" về khả năng của kernel; từ Windows 8.1 chỉ còn Windows Subsystem; gồm kernel32.dll, user32.dll, gdi32.dll, advapi32.dll, combase.dll..., chủ yếu là API được document chính thức.
- NTDLL.DLL: DLL system-wide hiện thực Native API, tầng user mode thấp nhất, chuyển sang kernel mode cho system call; cũng chứa Heap Manager, Image Loader và một phần user-mode thread pool.
- Service processes: giao tiếp với Service Control Manager (SCM, trong services.exe) để được start/stop/pause/resume; thường chạy dưới account local system, network service hoặc local service.
- Executive: tầng trên của NtOskrnl.exe (kernel), chứa phần lớn code kernel mode qua các "manager": Object Manager, Memory Manager, I/O Manager, Plug & Play Manager, Power Manager, Configuration Manager...; lớn hơn nhiều tầng Kernel bên dưới.
- Kernel: phần căn bản và nhạy cảm thời gian — thread scheduling, interrupt/exception dispatching, kernel primitive (mutex, semaphore); một phần viết bằng machine language riêng của CPU.
- Device drivers: kernel modules load được, chạy kernel mode với toàn quyền năng của kernel — chủ đề của cuốn sách.
- Win32k.sys: thành phần kernel mode của Windows subsystem, phụ trách UI và classic GDI (`CreateWindowEx`, `GetMessage`, `PostMessage`...); phần còn lại của hệ thống hầu như không biết gì về UI.
- HAL: lớp trừu tượng trên phần cứng gần CPU nhất, để driver không cần biết chi tiết Interrupt Controller hay DMA controller.
- System processes: process "có sẵn", ít được giao tiếp trực tiếp (Smss.exe, Lsass.exe, Winlogon.exe, Services.exe), một số là native processes (chỉ dùng Native API); terminating một số process này là fatal, gây crash.
- Subsystem process: Csrss.exe — helper của kernel quản lý process thuộc Windows subsystem; là critical process (bị kill là crash); mỗi session một instance (session 0 + session user đăng nhập).
- Hyper-V hypervisor: có trên Windows 10/Server 2016+ khi hỗ trợ Virtualization Based Security (VBS) — OS thường thành một VM do Hyper-V điều khiển, với VTL 0 (user/kernel mode bình thường) và VTL 1 (secure kernel + Isolated User Mode).
- WSL (từ Windows 10 1607): khác subsystem cũ POSIX/OS/2 (phải compile sang PE), WSL 1 chạy executable ELF của Linux as-is nhờ Pico process (address space rỗng, minimal) + Pico provider (driver) intercept và dịch từng Linux system call sang Windows equivalent; WSL 2 (từ Windows 10 2004) bỏ pico, dùng hybrid VM với Linux kernel thật — nhanh hơn, hết các edge case của WSL 1.

### Handles and Objects
- Kernel expose nhiều loại object cho user mode, kernel và driver; instance là data structure trong system space, do Object Manager (thuộc Executive) tạo khi được yêu cầu; object được reference counted — chỉ bị hủy khi reference cuối cùng được nhả.
- User mode truy cập gián tiếp qua handle: index vào handle table riêng của từng process (nằm trong kernel space) trỏ tới object; các hàm `Create*`/`Open*` trả về handle — `CreateMutex` tạo hoặc mở mutex tùy object có tên đã tồn tại chưa, `OpenMutex` trả null (0) nếu mutex tên đó không tồn tại.
- Ngoại lệ đáng nhớ: `CreateFile` trả `INVALID_HANDLE_VALUE` (-1) khi thất bại; handle là bội của 4, handle hợp lệ đầu tiên là 4, 0 không bao giờ hợp lệ.
- Kernel/driver dùng được cả handle lẫn pointer trực tiếp; `ObReferenceObjectByHandle` đổi handle thành pointer và tăng reference count nên không sợ user-mode client đóng handle giữa chừng gây dangling pointer; sau đó phải gọi `ObDereferenceObject` để giảm count — thiếu là leak chỉ hết khi boot lại.
- Object Manager duy trì handle count và tổng reference count; client xong việc phải đóng handle/dereference và coi handle/pointer là invalid; object bị hủy khi reference count về 0; mỗi object trỏ tới một object type (mỗi loại một type object), một số được expose qua exported global kernel variables trong kernel headers.

### Object Names
- Một số loại object có tên để mở bằng hàm Open; process/thread không có tên mà có ID (`OpenProcess`/`OpenThread` nhận identifier); tên file không phải tên object; thread "có tên" từ Windows 10 qua `SetThreadDescription` nhưng đó chỉ là friendly name phục vụ debug (Visual Studio hiển thị), không phải true name.
- Gọi hàm Create với tên: tạo object nếu chưa có, nếu đã có thì chỉ mở — khi đó `GetLastError` trả `ERROR_ALREADY_EXISTS` và handle nhận được là handle thêm cho object cũ.
- Tên truyền vào được prepend `\Sessions\x\BaseNamedObjects\` (x là session ID của caller), hoặc `\BaseNamedObjects\` nếu session 0; với AppContainer (thường là UWP) là `\Sessions\x\AppContainerNamedObjects\{AppContainerSID}` — tên object là session-relative (AppContainer thì package-relative); chia sẻ giữa các session bằng tiền tố `Global\` để tạo trong session 0 (ví dụ `Global\MyMutex` nằm dưới `\BaseNamedObjects`); AppContainer không có quyền dùng namespace session 0; xem namespace bằng Sysinternals WinObj (chạy elevated); object không tên không nằm trong cấu trúc này.
- Handle table của process xem được bằng Process Explorer/Handles; mặc định chỉ hiện handle có tên — bật Show Unnamed Handles and Mappings để xem hết; cột name chỉ là true name với Mutants (Mutexes), Semaphores, Events, Sections, ALPC Ports, Jobs, Timers, Directory...; với Process/Thread là ID, với File là tên file/device mà file object trỏ tới (khác object name — không lấy được handle tới file object cũ từ tên file, chỉ tạo được file object mới cùng file/device nếu sharing cho phép), với Key là registry path, với Token là user name.

### Accessing Existing Objects
- Cột Access trong Process Explorer hiển thị access mask dùng khi mở/tạo handle; mask quyết định thao tác được phép: muốn terminate process phải `OpenProcess` với ít nhất `PROCESS_TERMINATE`, khi đó `TerminateProcess` chắc chắn thành công.
- Cột Decoded Access mô tả access mask bằng chữ; double-click handle (hoặc Properties) xem properties của object chứ không phải handle: tên, type, địa chỉ kernel, số open handles, thông tin riêng của object (state, type của event object); mọi handle cùng trỏ một object thấy cùng thông tin.
- Giá trị References không phản ánh số reference thực (trước Windows 8.1 thì có); cách đúng là dùng kernel debugger: `!object` xem HandleCount/PointerCount rồi `!trueref` lấy RealPointerCount (ví dụ trong sách: HandleCount 2, PointerCount 65535, RealPointerCount 3).

## API / cấu trúc / hằng số quan trọng

| Tên | Loại | Vai trò & ghi chú ngắn |
|---|---|---|
| `CreateFile` | hàm | Mở/tạo file (kernel32.dll); thất bại trả `INVALID_HANDLE_VALUE` (-1) |
| `NtCreateFile` | hàm | Native API trong NTDLL.dll; đặt service number vào EAX rồi `syscall`/`sysenter` sang kernel |
| `CreateMutex` / `OpenMutex` | hàm | Tạo/mở mutex theo tên; trả 0 khi thất bại |
| `OpenProcess` / `TerminateProcess` | hàm | Kill process cần handle mở với tối thiểu `PROCESS_TERMINATE` |
| `CreateThread` / `NtCreateThreadEx` | hàm | Tạo thread; bản Win32 chỉ truyền một giá trị stack commit/reserve, bản native truyền được cả hai |
| `VirtualAlloc` / `NtAllocateVirtualMemory` | hàm | Cấp phát bộ nhớ; không chỉ định địa chỉ thì không đè vào vùng reserved |
| `ObReferenceObjectByHandle` | hàm | Đổi handle thành object pointer, tăng reference count, tránh dangling pointer |
| `ObDereferenceObject` | hàm | Giảm reference count; quên gọi là leak tới lần boot sau |
| `SetThreadDescription` | hàm | Đặt friendly name cho thread (Windows 10+), hữu ích khi debug |
| `PAGE_GUARD` | hằng số | Attribute của guard page, dùng để grow user stack qua page-guard exception |
| `LARGEADDRESSAWARE` | hằng số | Flag trong PE header, cho phép dùng address space > 2 GB |
| `ERROR_ALREADY_EXISTS` | hằng số | `GetLastError` khi Create với tên trùng object đã tồn tại |
| `PROCESS_TERMINATE` | hằng số | Access mask tối thiểu để terminate một process |
| SSDT (System Service Dispatch Table) | struct | Bảng mà system service dispatcher dùng EAX làm index để gọi system service |

## Code / mẫu thiết kế đáng nhớ

Terminate một process từ user mode — minh họa quy tắc handle phải mở với đúng access mask:

```c
bool KillProcess(DWORD pid) {
    // open a powerful-enough handle to the process
    HANDLE hProcess = OpenProcess(PROCESS_TERMINATE, FALSE, pid);
    if (!hProcess)
        return false;
    // now kill it with some arbitrary exit code
    BOOL success = TerminateProcess(hProcess, 1);
    // close the handle
    CloseHandle(hProcess);
    return success != FALSE;
}
```

Chuỗi system call (pseudocode theo mô tả sách): `CreateFile` (kernel32) → `NtCreateFile` (NTDLL, đặt service number vào EAX) → `syscall`/`sysenter` → system service dispatcher → SSDT[EAX] → `NtCreateFile` bản kernel (I/O manager) → trở về user mode. Mọi thao tác "không thuần tính toán" của app đều đi qua con đường này.

## Cạm bẫy & lưu ý

- `CreateFile` thất bại trả `INVALID_HANDLE_VALUE` (-1) trong khi đa số hàm khác trả null (0); 0 không bao giờ là handle hợp lệ và handle luôn là bội của 4.
- Quên `ObDereferenceObject` sau `ObReferenceObjectByHandle` là resource leak chỉ hết ở lần boot tiếp theo; driver leak system memory cũng vậy — không giải phóng khi unload.
- Kernel stack rất nhỏ (12/24 KB mặc định) và luôn resident trong RAM; user stack thì có thể bị page out.
- Truy cập trang Free/Reserved, system space từ user mode, hay ghi trang read-only đều gây access violation.
- Large pages cần RAM contiguous, non-pageable, chỉ có protection đọc/ghi; huge page 1 GB chỉ áp dụng khi allocation ≥ 1 GB và tìm được vùng contiguous.
- Handle user-mode đưa xuống driver phải được `ObReferenceObjectByHandle` thành pointer trước khi dùng; kill Csrss.exe hay một số system process là crash hệ thống.

## Tóm lại cần nhớ

- Process quản lý, thread thực thi: process chứa image, address space, primary token, handle table và các thread.
- Bộ nhớ ảo là relative theo process; page có ba state Free/Committed/Reserved; đơn vị quản lý là page 4 KB (large/huge page để tối ưu TLB).
- System space (kernel, HAL, drivers) là absolute, dùng chung toàn hệ thống và được bảo vệ khỏi user mode — code driver có tác động system-wide.
- System service là con đường để user mode yêu cầu kernel làm việc: NTDLL → `syscall`/`sysenter` với service number → SSDT.
- Mọi kernel object nằm trong system space, được reference counted; user mode chỉ chạm tới qua handle trong handle table của process.
- Tên object là session-relative, và mở object phải với đúng access mask cần thiết.
