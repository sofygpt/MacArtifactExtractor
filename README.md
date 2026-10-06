# Trích HfsPlus từ gói Apple macOS Tahoe bằng GitHub Actions

Bộ dự án cho runner tải `InstallAssistant.pkg` Tahoe từ catalog Apple, kiểm tra
chữ ký gói, giải nén firmware Mac Intel và trích driver `HfsPlus` x86_64. Đầu ra
có manifest và SHA-256 để đối chiếu nguồn gốc. Chưa chạy tải gói Apple thực tế
trên GitHub runner: các kiểm thử cục bộ không chứng minh firmware Tahoe hiện
tại chắc chắn có module này. Nếu không tìm được, workflow báo lỗi cùng log.

## Chạy lần đầu

1. Giải nén bộ dự án trên máy bạn. Tạo repository GitHub riêng cho công việc này.
   Có thể dùng repo private để lưu kết quả cho mục đích cá nhân.
2. Đưa **nội dung bên trong** `tahoe-hfsplus-actions/` vào gốc repository.
   Cần có `.github/workflows/extract-hfsplus.yml`, `scripts/` và `tests/`.
   Windows có thể ẩn thư mục `.github`; đừng bỏ sót nó.
3. Commit/push vào nhánh mặc định. Vào **Actions → Extract HfsPlus from Apple Tahoe
   → Run workflow**. Nếu GitHub yêu cầu bật Actions cho repository thì bật nó.
4. Lần đầu để trống các trường và bấm **Run workflow**. Workflow tự chọn bản
   Tahoe 26.x stable mới nhất đang có trong catalog Apple; không chọn macOS 27
   hoặc bản beta. Runner dùng `macos-15-intel`; hệ điều hành runner không cần là Tahoe.
5. Mở lần chạy để theo dõi. Khi hoàn tất, tải artifact
   `tahoe-hfsplus-<run_id>-<run_attempt>` ở cuối trang. Artifact giữ 7 ngày.

Nếu dùng git trên máy đã đăng nhập GitHub, sau khi tạo repo và clone repo trống,
chép nội dung dự án vào clone đó rồi chạy tại thư mục clone:

```bash
git add .github scripts tests docs examples README.md VERIFICATION.md .gitignore
git commit -m "Add Apple Tahoe HfsPlus extraction workflow"
git push
```

Không cần Apple ID, mật khẩu hoặc secret bổ sung. Workflow chỉ có quyền
`contents: read`; checkout không lưu token trong cấu hình git.

## Các trường trong Run workflow

| Trường | Ý nghĩa |
|---|---|
| `version` | Trống: chọn stable Tahoe mới nhất. Nhập `26.2` nếu muốn đúng phiên bản đó và Apple vẫn còn cung cấp. |
| `build` | Trống: không khóa build. Có thể nhập build cụ thể lấy từ `source.json` của lần chạy trước. |
| `firmware_name` | Trống: quét tất cả firmware Intel tìm thấy. Nhập tên chính xác như trong inventory để chỉ trích một firmware ở lần sau. |
| `ocbinary_commit` | Trống: không tải OcBinaryData. Nhập full commit SHA 40 ký tự để so sánh với `Drivers/HfsPlus.efi` tại commit đó. |

Các input đi qua biến môi trường và đối số được quote, không chèn trực tiếp vào
mã shell. Version/build được kiểm tra trước khi chọn nguồn.

## Đọc kết quả

| Tệp | Nội dung |
|---|---|
| `HfsPlus.efi` | Chỉ xuất hiện nếu mọi driver hợp lệ đã trích có cùng một SHA-256. |
| `candidates/HfsPlus-<sha256>.efi` | Từng binary độc lập; nếu có nhiều biến thể thì giữ riêng từng bản. |
| `manifest.json` | Trạng thái, URL Apple, product ID, phiên bản/build, hash gói/image/firmware/driver, phiên bản công cụ, nguồn của từng driver và kết quả đối chiếu. |
| `source.json` | Nguồn bộ cài được chọn và hash catalog/distribution. |
| `SHA256SUMS` | SHA-256 các tệp kết quả, log và manifest. |
| `firmware-inventory.json` | Tên firmware trong SharedSupport và ZIP để chọn `firmware_name`. |
| `firmware-scan.json` | Firmware đã thử, mã thoát UEFIExtract, số section hợp lệ và các section bị loại. |
| `logs/` | Kiểm tra chữ ký Apple, giải nén, mount/detach, UEFIExtract và đối chiếu nếu được yêu cầu. |
| `RESULT.txt` | Tóm tắt kết quả khi trích thành công. |

Nếu có nhiều biến thể, workflow vẫn trả các tệp trích thành công, nhưng không
tự đặt tên một bản bất kỳ thành `HfsPlus.efi`. Xem `sources` trong manifest và
rerun với một `firmware_name` đã ghi trong inventory. Nếu một firmware vẫn chứa
nhiều driver x64 khác nhau thì cần phân tích thêm, không tự chọn dựa vào tên Mac.

Kiểm tra checksum sau khi giải nén artifact:

```bash
# macOS
shasum -a 256 -c SHA256SUMS

# Linux
sha256sum -c SHA256SUMS
```

Nếu có `ocbinary_commit`, `comparison.status` sẽ là `match` hoặc `different`.
`match` chứng minh binary đã trích và binary ở commit được chọn giống nhau từng
byte; `different` có thể do phiên bản khác, không tự chứng minh có mã độc.
Driver vẫn là mã đóng của Apple. Việc trích và kiểm tra PE không phải kiểm toán bảo mật
hoặc kiểm chứng nó hoạt động trên Z840; không dùng file trích thay EFI đang chạy
trước khi có bản EFI dự phòng và thử trên phương tiện boot dự phòng.

## Những kiểm tra workflow thực hiện

- Chỉ tải từ các host software-update Apple cho catalog, distribution và package;
  chuyển URL HTTP cũ trong catalog sang HTTPS; kiểm tra host khi redirect.
- Khớp kích thước gói với catalog, dùng `pkgutil --check-signature` để yêu cầu
  gói được macOS tin cậy dưới chuỗi Apple Software Update. SHA-256 gói được
  ghi lại để tái lập; đây không phải checksum độc lập được Apple công bố.
- `pkgutil --expand-full` chỉ giải nén, không chạy script cài đặt và không nâng
  cấp OS. `hdiutil` mount SharedSupport read-only rồi detach trong cleanup.
- Trích firmware `.fd/.scap`, tìm GUID `AE4C11C8-1D6C-F24E-A183-E1CA36D1A8A9`,
  lấy body của PE32 section `0x10`. Binary phải có PE x86_64, PE32+ và subsystem
  EFI driver; không bao giờ thực thi driver đó.
- UEFIExtract **A75** từ LongSoft; ZIP universal mac được khóa bằng SHA-256
  `8cbdd6d42193d6fb8a0c37dc860b4695c618f923b8ecfff9c0042fbdd80aaa80`.
  Đây là tin cậy binary công cụ và checksum upstream, không phải tự build công cụ.
- Actions checkout/upload-artifact khóa bằng commit SHA. Runner OS/image vẫn
  do GitHub cập nhật; manifest lưu `ImageVersion` để biết môi trường lần chạy.
- Không đọc firmware host, flash BIOS, chỉnh EFI, ghi NVRAM hoặc dùng một
  binary từ OcBinaryData làm kết quả thay thế khi trích thất bại.

## Dung lượng và lỗi thường gặp

Full installer lớn; cần khoảng **2 × kích thước InstallAssistant.pkg + 8 GiB**
trống cho tải và giải nén. Workflow xóa các bundle Xcode có sẵn **chỉ trên runner
GitHub-hosted tạm thời**, vì tác vụ không cần Xcode. Script vẫn kiểm tra dung lượng
trước khi tải. Chạy trên máy Mac cá nhân không thực hiện bước xóa Xcode.

Không có ước lượng thời gian cố định: mạng, kích thước gói và số firmware khác nhau.
Job có timeout 180 phút; tải lỗi sẽ thử lại từ đầu tối đa 3 lần. Private repo dùng
quota/phí Actions của tài khoản bạn; kiểm tra quota trước khi chạy lại nhiều lần.

| Lỗi | Hướng xử lý |
|---|---|
| Không có matching stable Tahoe trong catalog | Để trống version/build hoặc kiểm tra bản yêu cầu còn được Apple cung cấp. Script không chuyển sang Sequoia. |
| Package signature bị từ chối | Đọc `logs/apple-signature.txt`; không bỏ kiểm tra chữ ký. Có thể cần cập nhật cách nhận diện chuỗi Apple nếu Apple đổi certificate. |
| Insufficient disk | Đọc số GiB cần/còn trống trong manifest; dùng runner có đủ dung lượng nếu xóa Xcode vẫn không đủ. |
| Không có SharedSupport.dmg hoặc không có firmware Intel | Cấu trúc gói có thể đã đổi. Kiểm tra source/inventory; cần cập nhật script theo gói thực tế. |
| UEFIExtract không thấy HfsPlus | Xem `firmware-scan.json` và log. Có thể firmware không chứa GUID này hoặc parser chưa hỗ trợ; không đổi tên module khác thành HfsPlus. |
| Kết quả `failed` nhưng có artifact | Artifact chứa hồ sơ chẩn đoán; kiểm tra status trong manifest trước khi dùng tệp. |

## Chạy trên Mac cục bộ

macOS với Python 3 và đủ dung lượng, chạy từ gốc dự án:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/extract_tahoe.py --output output
```

Nếu đã có `output/`, chọn thư mục mới bằng `--output output-next`; script không
ghi đè kết quả cũ. Không chạy script bằng sudo. Việc tải dùng catalog độc lập,
không dựa vào danh sách installer tương thích do `softwareupdate` trả cho model runner.

## Nguồn kỹ thuật và phạm vi đã kiểm tra

- [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
- [gibMacOS: cấu trúc catalog và distribution Apple](https://github.com/corpnewt/gibMacOS/blob/master/gibMacOS.py)
- [UEFIExtract: cú pháp GUID, body và section type](https://github.com/LongSoft/UEFITool/blob/new_engine/UEFIExtract/uefiextract_main.cpp)
- [LongSoft UEFITool A75](https://github.com/LongSoft/UEFITool/releases/tag/A75)
- [Ví dụ firmware payload trong bộ cài Apple](https://gist.github.com/startergo/18e7fc4f2b1125e80b677181cc6c77e7)
- [Ví dụ GUID HfsPlus và trích module](https://gist.github.com/cecekpawon/e38bda384ff115f09e638482849deb2d)
- [OpenCore Configuration: HfsPlus](https://github.com/acidanthera/OpenCorePkg/blob/master/Docs/Configuration.tex)

Kiểm thử trong Linux: chọn version/build, validation URL, signature output,
ZIP, PE và trường hợp nhiều binary. macOS pkgutil/hdiutil, tải multi-GB từ Apple,
UEFIExtract trên firmware Tahoe thật và GitHub Actions end-to-end cần lần chạy đầu
trên runner. Resolver đã chọn được gói Tahoe stable từ catalog/distribution Apple
thật; xem snapshot `examples/apple-source-2026-10-06.json` và `VERIFICATION.md`.
Không có binary Apple hoặc bộ cài macOS được đóng gói trong dự án này.
