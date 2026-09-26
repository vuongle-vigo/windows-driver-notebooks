# Chương 5: Debugging and Tracing

> Nguồn: *Windows Kernel Programming, 2nd Edition* — Pavel Yosifovich, trang 81–136

## Tổng quan
Chương này trang bị kỹ năng debug driver Windows: debug user-mode và kernel-mode bằng bộ Debugging Tools for Windows (trọng tâm là WinDbg) — từ cấu hình symbols, lệnh cơ bản, đến thiết lập kernel debugging hai máy host/target (target là VM) và đặt breakpoint trong driver. Điểm cốt lõi: kernel debugging là điều khiển cả máy — khi break, toàn hệ thống target bị freeze. Ngoài debugger, chương giới thiệu `NT_ASSERT` và các kỹ thuật logging lọc được, có ngữ nghĩa (`DbgPrintEx`, Trace Logging/ETW) để giảm phụ thuộc vào debugger.

## Nội dung theo từng mục

### Debugging Tools for Windows
- Package chứa 4 debugger: `Cdb.exe`/`Ntsd.exe` (user-mode console, khác nhau chỉ ở chỗ Ntsd luôn mở console mới), `Kd.exe` (kernel debugger console), `WinDbg.exe` (duy nhất có GUI, dùng cho cả user-mode và kernel debugging).
- WinDbg Preview (Microsoft Store, cần Windows 10 1607+) có UI tốt hơn, chức năng tương đương bản classic; mọi lệnh trong chương chạy được trên cả hai.
- Mọi debugger cùng dựa trên một debugger engine là `DbgEng.dll`; sức mạnh chính đến từ extension DLL nạp thêm lệnh; engine được tài liệu hóa để có thể tự viết debugger/tool. Cài đặt chỉ là copy file (không đụng Registry) nên dễ sao chép.
- Tool phụ: `Gflags.exe` (kernel/image flags), `ADPlus.exe` (dump khi crash/hang), `Kill.exe`, `Dumpchk.exe`, `TList.exe`, `Umdh.exe` (phân tích heap user-mode), `UsbView.exe`.

### Introduction to WinDbg
- WinDbg vận hành quanh lệnh: gõ lệnh → nhận kết quả dạng text; một phần kết quả hiển thị trong window riêng (locals, stack, threads).
- Ba loại lệnh: **intrinsic** (built-in trong engine, tác động lên target), **meta** (bắt đầu `.`, tác động lên môi trường debugging, ví dụ `.load` nạp extension DLL), **extension/bang** (bắt đầu `!`, hiện thực trong DLL ngoài — nguồn sức mạnh chính của debugger).
- Viết extension DLL khả thi và được tài liệu hóa; nhiều DLL sẵn có phục vụ kịch bản cụ thể.

### Tutorial: User mode debugging basics
- Hai cách bắt đầu: launch exe kèm debugger hoặc attach vào process có sẵn (tutorial: attach vào Notepad). Command window là cửa sổ chính; sau attach, process suspend trong breakpoint do debugger gây ra.
- Symbols là điều kiện sống còn: `.symfix` đặt nhanh symbol server Microsoft; tốt hơn là đặt `_NT_SYMBOL_PATH=SRV*c:\Symbols*http://msdl.microsoft.com/download/symbols` (đoạn giữa hai `*` là cache cục bộ) — Sysinternals, Visual Studio... cũng đọc biến này.
- `lm` liệt kê module kèm trạng thái symbols: `deferred` (mặc định, nạp khi cần), `pdb symbols`, `private pdb symbols` (có biến cục bộ — module tự build), `export symbols` (tên hàm có thể sai), `no symbols`. Ép nạp `.reload /f module.dll`; chẩn đoán `!sym noisy`; offset 4 chữ số hex trong call stack gần như chắc chắn là symbols sai.
- `~` liệt kê threads: thread hiện tại đánh dấu `.` (hiện trong prompt như `0:003>`), thread gây breakpoint gần nhất đánh dấu `#`. `k` hiện stack dạng `modulename!functionname+offset`; `~ns` chuyển thread, `~nk` xem stack thread khác. Stack có `ntdll!TppWorkerThread` là thread pool thread (Tpp = Thread Pool Private).
- Số mặc định là hex; `? expr` đổi cơ số (tiền tố `0n` thập phân, `0y` nhị phân).
- `!teb`/`!peb` xem TEB/PEB thân thiện (stack base/limit, ClientId, LastErrorValue, LastStatusValue...); `dt ntdll!_teb` xem struct thật — tên struct Windows có `_` đầu, nên luôn dùng dấu `_`; `dt` kèm địa chỉ cho giá trị thực; `dx -r1` là lệnh duyệt dữ liệu hiện đại (DML; bật bằng `.prefer_dml 1` nếu bị tắt).
- Breakpoints: `bp module!func` đặt, `bl` liệt kê (index, `e`/`d`, link tới `bd` disable và `bc` xóa), `g` chạy tiếp; `p` step over (F10), `t` step into (F11); Ctrl+Break break chủ động. `q` thoát (kill process); `.detach` ngắt không kill.
- Demo `bp kernel32!createfilew`: API thật là `CreateFileW`/`CreateFileA` (macro theo `UNICODE`; W là chuẩn). Calling convention x64: 4 tham số nguyên/con trỏ đầu ở RCX, RDX, R8, R9 — `r rcx` rồi `du @rcx` hiện tên file Unicode (`db` xem theo byte; `@` tham chiếu register).
- `bp ntdll!ntcreatefile` (native API luôn Unicode, nhận `UNICODE_STRING`): `u` cho thấy EAX = 0x55 là system service number, lệnh `syscall` chuyển sang kernel; không step được vào syscall từ user-mode. Giá trị trả về trong EAX/RAX (với syscall là NTSTATUS); `!error @eax` dịch ra text (0xC0000034 = Object Name not found).

### Kernel Debugging
- Kernel debugging là điều khiển toàn máy: breakpoint hit → cả máy freeze, nên cần hai máy: **host** (chạy debugger) và **target** (bị debug); target thường là VM trên chính host — cấu hình khuyến nghị cho việc phát triển driver.

### Local Kernel Debugging
- LKD cho phép xem bộ nhớ/thông tin hệ thống trên chính máy nhưng **không đặt được breakpoint** — luôn nhìn trạng thái đang biến đổi, dữ liệu có thể stale; full KD chỉ nhận lệnh khi target đang break nên trạng thái ổn định.
- Bật: `bcdedit /debug on` (elevated) rồi restart. Bị Secure Boot chặn trên Windows 10/Server 2016 trở lên — phải tắt trong BIOS, hoặc dùng Sysinternals LiveKd (`livekd -w`; dữ liệu dễ stale, thỉnh thoảng phải thoát và chạy lại debugger).
- Sau restart, chạy WinDbg elevated → Attach To Kernel → tab Local; prompt hiển thị `lkd`.

### Local kernel Debugging Tutorial
- `!process 0 0` liệt kê mọi process: địa chỉ EPROCESS, SessionId, Cid (PID), Peb (địa chỉ user space), ParentCid (parent có thể đã chết), DirBase (physical address của Master Page Directory — x64: Page Map Level 4), ObjectTable, HandleCount, Image.
- Tham số của `!process`: (1) EPROCESS address hoặc PID (0 = tất cả); (2) detail bitmask (0 = ít nhất); (3) tên exe để lọc. Detail 1 thêm thông tin bộ nhớ/token/job (nhiều giá trị là DML hyperlink, click Job chạy `!job`); detail 2 liệt kê threads kèm đối tượng đang wait; 4, 8 hoặc tổ hợp (3) cho thêm; bỏ detail → full details kèm stack từng thread (theo địa chỉ ETHREAD).
- Kiến trúc thật của job là `EJOB` — xem đầy đủ bằng `dt nt!_ejob <addr>`.
- Xem bộ nhớ user space (ví dụ PEB) phải đặt process context trước: `.process /p <addr>` rồi `!peb`. User-mode symbols mặc định không nạp (stack chỉ hiện số) — `.reload /user` sau khi đặt context.
- Thread xem riêng bằng `!thread <ETHREAD>`; tiền tố `nt` thay cho tên module kernel thật (khác nhau giữa 64/32-bit, và ngắn hơn).
- Lệnh hữu ích khác: `!pcr` (PCR của processor), `!vm` (thống kê bộ nhớ), `!running` (thread đang chạy trên các CPU).

### Full Kernel Debugging
- Cần cấu hình cả host và target; media kết nối: **network** (nhanh nhất, cần Windows 8+ cả hai phía) hoặc **COM ảo map ra named pipe** trên host (cho target Windows 7; mọi nền tảng ảo hóa đều redirect được). Secure Boot không dùng được với full KD — **không có workaround**.
- **Using a Virtual Serial Port (COM) — target**: `bcdedit /debug on` + `bcdedit /dbgsettings serial debugport:1 baudrate:115200` rồi restart; Hyper-V Gen 1 cấu hình serial → named pipe qua UI settings, Gen 2 bằng PowerShell `Set-VMComPort myvmname -Number 1 -Path "\\.\pipe\debug"` (kiểm tra bằng `Get-VMComPort`). **Host**: Attach To Kernel → tab COM, nhập cùng thông số, bấm Break nếu chưa tự nối. Kết luận: map đúng COM number trong VM ra một named pipe unique trên host.
- Khi break, prompt dạng `0: kd>` — số bên trái là CPU gây break; nhớ rằng target frozen hoàn toàn trong suốt thời gian đó.
- **Using the Network (NET) — target**: `bcdedit /dbgsettings net hostip:<ip> port:<port> [key:<key>]` rồi restart (port khuyến nghị ≥ 50000; bỏ key thì tự sinh ngẫu nhiên, có thể tự đặt dạng `a.b.c.d` — chấp nhận được với VM cục bộ; xem lại bằng `bcdedit /dbgsettings`). **Host**: tab NET nhập cùng thông tin; có thể phải bấm Break vài lần mới nối được.

### Kernel Driver Debugging Tutorial
- Dùng driver Booster (chương 4): install (chưa load) trên target, copy PDB cạnh SYS để có symbols. Không thể đặt `bp` vào `DriverEntry` sau khi load (hàm đã chạy) → dùng `bu booster!driverentry`: **unresolved breakpoint**, debugger tự đánh giá lại mỗi khi có module mới nạp.
- `g` rồi `sc start booster` → breakpoint hit, source tự mở; debug theo dòng source với Locals/Watch (sửa giá trị được), F9 đặt breakpoint (thực chất sinh lệnh `bp` trong Command window).
- `k` cho thấy đường gọi `DriverEntry`: `GsDriverEntry` → `nt!PnpCallDriverEntry` → `nt!IopLoadDriver` → `nt!IopLoadUnloadDriver` → `nt!ExpWorkerThread` → `nt!PspSystemThreadStartup` → `nt!KiStartSystemThread` (system thread).
- Breakpoint không hit thường do symbols: chạy `.reload`; muốn đặt breakpoint ở user space thì chạy `.reload /user` trước. Breakpoint điều kiện theo process: `bp /p <EPROCESS> booster!boosterwrite` (tìm EPROCESS bằng `!process 0 0 explorer.exe`) — chỉ hit khi đúng process đó chạy code.
- `.detach` (hoặc Stop Debugging, có thể bấm nhiều lần) để ngắt khỏi target.

### Asserts and Tracing
Mục tiêu: giảm nhu cầu dùng debugger bằng asserts và logging dùng được cho cả Debug lẫn Release build.

#### Asserts
- `NT_ASSERT(expr)` (WDK header): expr sai (zero) → có kernel debugger: raise assertion breakpoint để debug ngay; không có debugger: system bugcheck, dump chỉ đúng dòng assert fail.
- Chỉ biên dịch biểu thức ở **Debug build** → gần như miễn phí về hiệu năng, nhưng biểu thức **cấm có side effect**: `NT_ASSERT(NT_SUCCESS(IoCreateSymbolicLink(...)))` sai vì lời gọi biến mất ở Release; cách đúng là gọi trước, gán `status`, rồi assert. Nên dùng assert thoải mái vì lý do này.

#### Extended DbgPrint
- `DbgPrint`/`KdPrint`: không lọc được output; tương đối chậm — vì thế thường dùng `KdPrint` để overhead biến mất ở Release, nhưng một số bug chỉ xảy ra ở Release nên output ở đó cũng rất quan trọng; chỉ là text không ngữ nghĩa; không có ghi file built-in (DebugView thì có); giới hạn cứng **512 byte**, phần thừa bị mất.
- `DbgPrintEx(ComponentId, Level, Format, ...)` (macro `KdPrintEx`) thêm lọc. ComponentId liệt kê trong `<dpfilter.h>`: 155 giá trị (0–154), phần lớn dành cho kernel/Microsoft; driver thứ ba dùng `DPFLTR_IHVDRIVER_ID` (77); ID chuyên biệt: IHVVIDEO 78, IHVAUDIO 79, IHVNETWORK 80, IHVSTREAMING 81, IHVBUS 82; `DPFLTR_DEFAULT_ID` (101) dùng cho `DbgPrint`.
- Level 0–31 được hiểu là bit `1 << Level`; >31 dùng nguyên giá trị. Hằng số sẵn có: `DPFLTR_ERROR_LEVEL` 0, `DPFLTR_WARNING_LEVEL` 1, `DPFLTR_TRACE_LEVEL` 2, `DPFLTR_INFO_LEVEL` 3.
- Output đi qua nếu `value & mask(component)` khác 0; mask đọc từ registry key **Debug Print Filter** lúc boot, mặc định 0 → hiệu lực thực tế là 1 (chỉ ERROR đi qua). Đặt mask theo 3 cách: (1) DWORD registry dưới `HKLM\System\CCS\Control\Session Manager\Debug Print Filter`, tên là phần giữa của macro (vd "IHVVIDEO"); (2) qua kernel debugger: `ed Kd_IHVVIDEO_Mask 0x1ff` (toàn cục: `Kd_WIN2000_Mask`); (3) native API undocumented `NtSetDebugFilterState` — caller user-mode cần **Debug privilege**. Kernel-mode có cặp `DbgQueryDebugFilterState`/`DbgSetDebugFilterState` trong `<wdm.h>` (undocumented) để driver tự đổi filter.
- `DbgPrint` thực chất là `DbgPrintEx(DPFLTR_DEFAULT_ID, DPFLTR_INFO_LEVEL, ...)` — giải thích vì sao registry cần `DEFAULT = 8` (1 << 3) để output đi qua.
- Vì mỗi lời gọi `DbgPrintEx` dài, sách bọc thành wrapper: `enum class LogLevel { Error, Warning, Information, Debug, Verbose }` (giá trị < 32 nên tự thành bit) và các hàm `Log`, `LogError`, `LogWarning`, `LogInfo`, `LogDebug` hiện thực bằng `vDbgPrintEx` (nhận `va_list`) với `DPFLTR_IHVDRIVER_ID`; `static_cast` bắt buộc cho scoped enum; giá trị trả về khai báo `ULONG` nhưng thực chất là NTSTATUS. Code mẫu nằm trong project **Booster2**.

#### Using Dbgkflt
- `Dbgkflt` (thư mục Tools trong repo samples của sách) query/đặt level qua `NtQueryDebugFilterState`/`NtSetDebugFilterState`, dùng được cả khi không có debugger: `dbgkflt default` (query), `dbgkflt default 0xf` (đặt 4 bit đầu); giá trị nhập luôn OR với 0x80000000 để bits dùng trực tiếp thay vì hiểu là 1 << n; cần chạy elevated.

#### Other Debugging Functions
- `vDbgPrintEx`: giống `DbgPrintEx` nhưng nhận `va_list` dựng sẵn (cho wrapper variadic); macro tương ứng `vKdPrintEx` chỉ biên dịch ở Debug.
- `vDbgPrintExWithPrefix`: tự thêm một **prefix** vào mọi output — giúp phân biệt driver của mình với driver khác và lọc dễ trong DebugView; nên để wrapper `Log` tự thêm prefix thay vì viết tay đầu mỗi chuỗi.

#### Trace Logging
- Trace Logging dựa trên **ETW**: hiệu năng cao (hàng nghìn events/giây không trễ đáng kể), mang thông tin ngữ nghĩa/typed mà text `DbgPrint` không có, capture live hoặc ghi file, dùng y hệt ở user-mode. Không cần đăng ký provider kiểu "classic" vì metadata nằm ngay trong event (self-describing).
- Khai báo provider: `TRACELOGGING_DEFINE_PROVIDER(g_Provider, "Booster", (guid...))` với GUID tự tạo (Create GUID tool của Visual Studio); kèm `#include <TraceLoggingProvider.h>`, `<evntrace.h>`; `TraceLoggingRegister` trong `DriverEntry`, `TraceLoggingUnregister` trong unload.
- Ghi event: `TraceLoggingWrite(g_Provider, "tên event", TraceLoggingLevel(TRACE_LEVEL_INFORMATION), TraceLoggingValue(...), TraceLoggingUnicodeString(RegistryPath, "RegistryPath"), TraceLoggingNTStatus(status, "Status"), ...)`. `TraceLoggingValue` tổng quát nhất (suy type từ đối số đầu); các macro typed khác đảm bảo an toàn kiểu (UInt32, Int32, UnicodeString, NTStatus...).

#### Viewing ETW Traces
- Events mặc định bị drop — cần một session lắng nghe. Tool **TraceView.exe** (WDK, copy được sang target): tạo new log session, thêm provider bằng "Manually Entered Control GUID", decoding để chế độ Auto (trace logging không cần nguồn ngoài), chọn output real-time và/hoặc file; file log mở lại bằng TraceView sau này.
- Có thể dùng tool ETW khác hoặc tự viết tool parse log, vì event có semantic information nên dễ phân tích.

## API / cấu trúc / hằng số quan trọng
| Tên | Loại | Vai trò & ghi chú ngắn |
|---|---|---|
| `DbgEng.dll` | struct (engine DLL) | Debugger engine chung đằng sau mọi debugger của package |
| `bp`/`bu`/`bl`/`bd`/`bc` | hằng số (lệnh) | Đặt breakpoint / unresolved bp (driver chưa load) / liệt kê / disable / xóa |
| `g`,`p`,`t`,`k`,`u`,`r`,`?`,`~` | hằng số (lệnh) | Go; step over; step into; stack; disassemble; registers; evaluate; threads |
| `dt`/`dx`/`db`/`du` | hằng số (lệnh) | Display type (giữ `_` đầu tên struct); duyệt dữ liệu hiện đại; dump bytes; dump Unicode |
| `.process /p`, `.reload /user`, `.reload /f` | macro | Đặt process context trước khi xem user space; nạp user symbols; ép nạp symbols module |
| `!process`, `!thread`, `!teb`, `!peb`, `!job`, `!pcr`, `!vm`, `!running` | hàm | Truy vấn process/thread/TEB/PEB/job/PCR/bộ nhớ/CPU trong kernel debugging |
| `_NT_SYMBOL_PATH` | hằng số | `SRV*<cache>*http://msdl.microsoft.com/download/symbols` |
| `bcdedit /debug on`, `/dbgsettings serial\|net` | hằng số (lệnh) | Bật kernel debugging; cấu hình COM (baudrate 115200) hoặc NET (hostip/port/key) |
| `EPROCESS`, `ETHREAD`, `_TEB`, `_PEB`, `EJOB` | struct | Struct kernel hiển thị qua `!process`/`!thread`/`!teb`/`!peb`/`dt nt!_ejob` |
| `NT_ASSERT` | macro | Assert kernel; chỉ biên dịch expr ở Debug; fail → breakpoint hoặc bugcheck |
| `DbgPrint`/`KdPrint` | hàm/macro | Print thô; KdPrint chỉ Debug; giới hạn 512 byte; không lọc |
| `DbgPrintEx`/`KdPrintEx`/`vDbgPrintEx` | hàm/macro | Print có `(ComponentId, Level)` để lọc; biến thể nhận `va_list` |
| `vDbgPrintExWithPrefix`/`vKdPrintEx` | hàm/macro | Tự thêm prefix vào output; bản Kd chỉ Debug |
| `DPFLTR_IHVDRIVER_ID` (77), `DPFLTR_DEFAULT_ID` (101) | hằng số | Component ID chuẩn cho driver thứ ba / mặc định của DbgPrint |
| `DPFLTR_ERROR/WARNING/TRACE/INFO_LEVEL` (0–3) | hằng số | Mức level; 0–31 → bit `1 << Level`, >31 dùng nguyên |
| `NtSetDebugFilterState`/`NtQueryDebugFilterState` | hàm | Native API (undocumented) đổi debug filter; user-mode caller cần Debug privilege |
| `DbgSetDebugFilterState`/`DbgQueryDebugFilterState` | hàm | Bản kernel-mode trong `<wdm.h>` (undocumented) |
| `TRACELOGGING_DEFINE_PROVIDER` | macro | Định nghĩa ETW TraceLogging provider (tên + GUID) |
| `TraceLoggingRegister`/`TraceLoggingUnregister` | hàm | Đăng ký/hủy provider trong `DriverEntry`/unload |
| `TraceLoggingWrite` | macro | Ghi event với property typed (`TraceLoggingValue`, `UnicodeString`, `NTStatus`, `UInt32`...) |

## Code / mẫu thiết kế đáng nhớ
1. Wrapper logging có prefix, dùng cho mọi driver:
```cpp
ULONG Log(LogLevel level, PCSTR format, ...) {
    va_list list;
    va_start(list, format);
    return vDbgPrintExWithPrefix("Booster2", DPFLTR_IHVDRIVER_ID,
        static_cast<ULONG>(level), format, list);
}
```
Gọi thay `DbgPrintEx` để được level rõ ràng, component ID chuẩn và prefix tự động trong mọi output.
2. Assert không side effect:
```cpp
status = IoCreateSymbolicLink(...);
NT_ASSERT(NT_SUCCESS(status));   // không gọi API bên trong NT_ASSERT
```
Lời gọi API đặt trong `NT_ASSERT` sẽ biến mất ở Release build.
3. Ghi event Trace Logging:
```cpp
TraceLoggingWrite(g_Provider, "Boosting",
    TraceLoggingLevel(TRACE_LEVEL_INFORMATION),
    TraceLoggingUInt32(data->ThreadId, "ThreadId"),
    TraceLoggingInt32(oldPriority, "OldPriority"),
    TraceLoggingInt32(data->Priority, "NewPriority"));
```
Logging hiệu năng cao, có kiểu dữ liệu, xem bằng TraceView hoặc tool ETW khác.

## Cạm bẫy & lưu ý
- Output `DbgPrint(Ex)` giới hạn 512 byte — phần thừa bị mất im lặng.
- Không bao giờ đặt lời gọi có side effect bên trong `NT_ASSERT` — biểu thức không tồn tại ở Release build.
- Level nhỏ hơn 32 bị hiểu là bit (`1 << Level`); registry Debug Print Filter mặc định 0 → hiệu lực 1, nên theo mặc định chỉ output level ERROR đi qua.
- LKD và full kernel debugging đều không dùng được khi bật Secure Boot; full KD hoàn toàn không có workaround (LKD còn có LiveKd).
- LKD không đặt breakpoint được và dữ liệu có thể stale; trong full KD, mọi break freeze toàn bộ máy target.
- Xem bộ nhớ user space khi kernel debugging: bắt buộc `.process /p` đặt process context trước, và `.reload /user` để có user-mode symbols (nếu không stack user chỉ hiện địa chỉ trần).
- Triệu chứng symbols sai: offset lớn trong call stack (offset 4 chữ số hex gần như chắc chắn sai); tên struct luôn dùng dấu `_` đầu (`dt nt!_teb`).
- Trả về của biến thể `DbgPrint` khai báo `ULONG` nhưng thực chất là NTSTATUS; scoped enum (`enum class`) phải `static_cast` sang số nguyên.
- Đặt breakpoint vào `DriverEntry` bằng `bp` sau khi load là quá muộn — phải dùng `bu` (unresolved breakpoint) trước khi `sc start`.

## Tóm lại cần nhớ
- Debug driver = debug cả máy: full kernel debugging theo mô hình host–target (target là VM) là setup chuẩn; LKD chỉ để xem, không break được.
- Symbols đúng là điều kiện tiên quyết của mọi debugging — đặt `_NT_SYMBOL_PATH` một lần và hưởng lợi trên nhiều tool.
- `bu` cho driver chưa load là cách chuẩn để break ngay trong `DriverEntry`; breakpoint điều kiện `bp /p` thu hẹp theo process.
- Kết hợp `NT_ASSERT` (chỉ Debug, không side effect) + wrapper `DbgPrintEx` có mức lọc + Trace Logging (ETW) giúp giảm nhu cầu debugger, và logging vẫn hoạt động ở Release build.
- Trace Logging vượt trội về hiệu năng và ngữ nghĩa so với text logging; events mặc định bị drop, cần TraceView (hoặc tool tự viết) để thu và xem.
