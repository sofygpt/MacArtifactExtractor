# Phạm vi kiểm chứng — 2026-10-06

- `python3 -m unittest discover -s tests -v`: **19 tests passed** trên Python 3.12/Linux.
- Python compilation và CLI `--help`: đạt.
- Workflow YAML: parse được; manual dispatch, runner Intel và quyền contents/read đã kiểm tra.
- Endpoint catalog Apple đúng trả HTTP **200**, là plist với IndexDate 2026-10-02.
- Resolver đã chạy với catalog/distribution Apple thật và chọn gói Tahoe 26.x
  stable. Snapshot metadata được lưu trong `examples/apple-source-2026-10-06.json`;
  đây là kết quả lần kiểm tra, không phải cam kết catalog luôn chọn cùng bản.
- URL InstallAssistant.pkg đã kiểm tra bằng HTTP Range: trả **206**, tổng kích
  thước **18,380,974,544 byte** khớp catalog và header `xar!` đúng định dạng PKG.
  Chỉ đọc 32 byte, chưa kiểm tra chữ ký của toàn gói.
- Download thật ZIP UEFIExtract A75 universal mac: 1,515,640 byte, SHA-256
  `8cbdd6d42193d6fb8a0c37dc860b4695c618f923b8ecfff9c0042fbdd80aaa80`, khớp pin.
- Rà soát độc lập xác minh upstream A75 xuất cả `body.bin` lẫn `body_N.bin`;
  test dùng subprocess fixture bảo đảm không bỏ sót nhiều section trong một firmware.
- Chưa chạy pkgutil/hdiutil, chưa tải/giải nén full Tahoe, chưa thực thi UEFIExtract
  macOS trên firmware Tahoe thật, chưa chạy workflow trong tài khoản GitHub của bạn.

Kiểm thử dùng binary PE tổng hợp và ZIP fixture, không dùng driver Apple thật.
Kết quả kiểm thử không chứng minh driver an toàn, tương thích Z840 hoặc có cùng
phiên bản với binary OcBinaryData. Lần chạy runner phải được đánh giá bằng
`manifest.json`, `firmware-scan.json`, chữ ký gói và checksum đầu ra.
