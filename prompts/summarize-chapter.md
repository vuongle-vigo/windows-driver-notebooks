# Prompt mẫu: Tóm tắt một chương sách thành file Markdown

> Dùng file này làm **prompt gốc** để giao cho mỗi agent (subagent) tóm tắt **một chương** của sách
> `Windows Kernel Programming, 2nd Edition (Pavel Yosifovich).pdf`.
> Khi giao việc, chỉ cần thay các biến ở bảng dưới bằng giá trị của chương đó, phần còn lại giữ nguyên.

## Biến cần thay khi giao việc

| Biến | Ý nghĩa | Ví dụ |
|---|---|---|
| `{{CHAPTER_NUM}}` | Số thứ tự chương | `5` |
| `{{CHAPTER_TITLE}}` | Tên chương gốc (tiếng Anh) | `Debugging and Tracing` |
| `{{INPUT_TXT}}` | Đường dẫn tuyệt đối tới file text đã trích của chương | `C:\Users\Zed\Documents\GitHub\windows-driver-notebooks\extracted\ch05-debugging-and-tracing.txt` |
| `{{OUTPUT_MD}}` | Đường dẫn tuyệt đối file tóm tắt đầu ra (cùng tên với file input, đuôi `.md`, đặt trong `summaries/`) | `C:\Users\Zed\Documents\GitHub\windows-driver-notebooks\summaries\ch05-debugging-and-tracing.md` |
| `{{PAGE_RANGE}}` | Trang PDF tương ứng của chương | `81–136` |

> Nếu file `{{INPUT_TXT}}` chưa tồn tại, tạo lại toàn bộ bằng lệnh `py tools/extract_chapters.py`
> (chạy ở thư mục gốc repo, cần Python + PyMuPDF). Script tự dò mục lục từ bookmark của PDF.

---

## Phần prompt gửi cho agent (copy nguyên khối này, đã thay biến)

Bạn là kỹ sư Windows kernel giàu kinh nghiệm, đồng thời là người viết tài liệu kỹ thuật cẩn thận.
Nhiệm vụ: tóm tắt **Chương {{CHAPTER_NUM}} — "{{CHAPTER_TITLE}}"** (trang {{PAGE_RANGE}}) của sách
*Windows Kernel Programming, 2nd Edition — Pavel Yosifovich* thành file Markdown tại `{{OUTPUT_MD}}`.

### Bước 1 — Đọc HẾT chương, không đọc tắt

1. Đọc file `{{INPUT_TXT}}` **toàn bộ**. File chứa toàn bộ text của chương, đánh dấu theo trang bằng
   dòng `===== [PDF page N] =====`. Nếu dài hơn 2000 dòng thì đọc tiếp nhiều lần bằng `offset` cho đến
   hết file — **cấm** tóm tắt dựa trên tiêu đề mục hoặc suy đoán.
2. Trong lúc đọc, lập danh sách mọi mục (heading) và mục con của chương, vì đây là checklist bắt buộc.

### Bước 2 — Viết file tóm tắt theo mẫu ở dưới

Ngôn ngữ: **tiếng Việt**, nhưng **giữ nguyên tiếng Anh** mọi thuật ngữ, tên hàm/API, tên struct,
macro, hằng số, flag (ví dụ: `DriverEntry`, `IRQL`, `DRIVER_OBJECT`, `ExAllocatePool2`,
`PASSIVE_LEVEL`, `Irp->RequestorMode`…). Tên file/đoạn code chép đúng nguyên văn.

Mẫu bắt buộc của `{{OUTPUT_MD}}`:

```markdown
# Chương {{CHAPTER_NUM}}: {{CHAPTER_TITLE}}

> Nguồn: *Windows Kernel Programming, 2nd Edition* — Pavel Yosifovich, trang {{PAGE_RANGE}}

## Tổng quan
2–4 câu: chương giải quyết vấn đề gì, cơ chế cốt lõi, và vai trò của nó trong lập trình driver.

## Nội dung theo từng mục
<!-- LẶP khối này cho MỌI mục của chương gốc, đúng thứ tự, không bỏ mục nào -->

### <Tên mục gốc, giữ tiếng Anh>
- Ý chính của mục, mỗi bullet một ý, viết câu hoàn chỉnh.
- Cơ chế hoạt động / lý do tồn tại của kỹ thuật (không chỉ liệt kê tên).
- Số liệu, bảng, quy ước quan trọng (ví dụ: mức IRQL, giá trị timeout, quyền truy cập...).

## API / cấu trúc / hằng số quan trọng
| Tên | Loại | Vai trò & ghi chú ngắn |
|---|---|---|
<!-- mọi hàm, struct, macro được sách trình bày chi tiết; loại thực tế: hàm / struct / macro / hằng số -->

## Code / mẫu thiết kế đáng nhớ
1–3 khối code ngắn (chép từ sách hoặc pseudocode trung thực), mỗi khối kèm 1–2 câu giải thích khi nào dùng.
Nếu chương không có code đáng nhớ thì bỏ mục này.

## Cạm bẫy & lưu ý
- Các lỗi thường gặp, ràng buộc IRQL, vấn đề bộ nhớ/đồng bộ mà sách cảnh báo. Bỏ mục này nếu chương không có.

## Tóm lại cần nhớ
- 3–6 bullet chốt tinh thần chương.
```

### Bước 3 — Tự kiểm tra trước khi báo xong

- [ ] **Đủ mục**: đối chiếu lại — mọi heading của chương gốc đều xuất hiện trong mục
      "Nội dung theo từng mục" (tiêu đề "Summary" của chương gộp vào "Tóm lại cần nhớ").
- [ ] **Đủ ý quan trọng**: mỗi mục có ít nhất 2–4 bullet, nêu được *cách hoạt động* chứ không chỉ *tên kỹ thuật*.
- [ ] **Không bịa**: mọi chi tiết đều có trong text gốc; không thêm kiến thức ngoài chương.
- [ ] Đúng mẫu, đúng ngôn ngữ (Việt + thuật ngữ Anh), file ghi UTF-8.

### Quy định độ dài

- Chương ≤ 25 trang: khoảng **400–700 từ**.
- Chương 25–50 trang: khoảng **700–1100 từ**.
- Chương > 50 trang: khoảng **1100–1600 từ**.
- Độ phủ ý quan trọng hơn đúng con số: cứ viết đủ ý rồi cắt chữ thừa (bỏ lời dẫn, ví dụ lặp lại,
  mô tả ảnh chụp màn hình, hướng dẫn click GUI từng bước — chỉ chốt lại kết luận của phần đó).

### Báo cáo khi xong

Trả về trong message cuối: đường dẫn file đã viết, số từ ước lượng, danh sách mục gốc đã bao phủ,
và ghi rõ nếu có chỗ bạn không chắc chắn.

---

## Cách gọi agent (ví dụ lời nhắn điều phối)

```text
Đọc file C:\Users\Zed\Documents\GitHub\windows-driver-notebooks\prompts\summarize-chapter.md
và thực hiện đúng toàn bộ quy trình trong đó với các giá trị sau:
- {{CHAPTER_NUM}} = 5
- {{CHAPTER_TITLE}} = Debugging and Tracing
- {{INPUT_TXT}} = C:\Users\Zed\Documents\GitHub\windows-driver-notebooks\extracted\ch05-debugging-and-tracing.txt
- {{OUTPUT_MD}} = C:\Users\Zed\Documents\GitHub\windows-driver-notebooks\summaries\ch05-debugging-and-tracing.md
- {{PAGE_RANGE}} = 81–136
```

Mỗi chương là một agent độc lập, có thể chạy song song.
