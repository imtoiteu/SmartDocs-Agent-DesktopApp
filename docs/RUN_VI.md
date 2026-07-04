# Chạy SmartDocs-Agent (Tiếng Việt)

Hướng dẫn thực hành để chạy SmartDocs-Agent trên máy cục bộ bằng các script
trong `scripts/`. Các script tự động tìm virtualenv Python và đường dẫn dự án —
**bạn không cần kích hoạt venv hay `cd` vào đâu cả.**

> GLM OCR là **tuỳ chọn** và chỉ chạy trên Apple Silicon (MLX). Ứng dụng web và
> các engine Legacy / VietOCR / Modern vẫn hoạt động bình thường khi không có GLM.
> **Linux / Windows:** xem [INSTALLATION.md](INSTALLATION.md) và ma trận hỗ trợ nền
> tảng trong README — mọi thứ dưới đây (trừ GLM MLX server) đều áp dụng
> (Windows cần Git Bash hoặc WSL để chạy `scripts/*.sh`).

---

## 0. Quy trình clone sạch (macOS Apple Silicon)

Chuỗi lệnh đầy đủ từ số 0 — clone đến chạy app. Chạy một lần khi có mạng;
sau đó app hoạt động hoàn toàn offline.

**Yêu cầu trước — Python 3.10.** Venv chính BẮT BUỘC dùng Python 3.10
(3.12/3.13/3.14 không cài được `paddlepaddle`/`Pillow 10.2.0`; `setup.sh` sẽ
từ chối thay vì tạo venv hỏng):

```bash
brew install python@3.10
```

```bash
git clone <repo-url> SmartDocs-Agent
cd SmartDocs-Agent
chmod +x scripts/*.sh tools/*.sh        # git thường giữ sẵn quyền này; chắc ăn thì chạy
cp .env.example .env                    # mặc định là đủ để test cục bộ

scripts/setup.sh                        # 1. venv chính + requirements + thư mục
scripts/setup_glm.sh --precache-layout  # 2. venv GLM + mô hình layout (Apple Silicon)
scripts/setup_offline.sh                # 3. TẤT CẢ mô hình AI offline (Qwen 1.5B, PhoBERT,
                                        #    embeddings, VietOCR weights+config, Argos, Paddle)
scripts/check.sh                        # 4. kiểm tra môi trường / runtime
scripts/check_offline.sh                # 5. kiểm tra mô hình + smoke test dịch Argos THẬT

scripts/start_glm.sh -b                 # 6. GLM MLX server chạy nền (logs/glm.log)
scripts/start.sh                        # 7. web app (foreground) → http://localhost:5002
```

Đăng nhập bằng tài khoản seed lần đầu — **đổi mật khẩu ngay**:
`admin / admin123` (quản trị) hoặc `user / user123`; quản lý trong `/admin`.

**Sau các bước trên, tất cả những mục sau phải hoạt động** (danh sách nghiệm thu
clone sạch):

- đăng nhập, upload, quản lý tài liệu
- PaddleOCR **Legacy** và **Modern** (mô hình đã cache ở bước 3)
- **VietOCR** (weights + `models/vietocr/config.yml` từ bước 3)
- **GLM OCR** (MLX server bước 6 + mô hình layout bước 2)
- **Chat**, **AI Rewrite** và **Agent** trên **Qwen 2.5 1.5B** cục bộ (không bao
  giờ được tải mô hình 3B)
- dịch **online** (Google, cần mạng) và dịch **offline** (Argos — bước 5 đã smoke
  test thật en→vi và vi→en)
- tóm tắt (PhoBERT + fallback trích xuất), embeddings RAG ngữ nghĩa

Nếu dòng nào của `scripts/check_offline.sh` là ❌, thông báo sẽ nêu đúng lệnh cần
chạy lại — sửa xong mới test UI.

---

## 1. Cài đặt lần đầu

```bash
scripts/setup.sh
```

Script này sẽ:

- tìm virtualenv có sẵn (`./.venv` hoặc `../.venv` ở thư mục cha), hoặc tạo mới
  `./.venv` nếu chưa có — không bao giờ ghi đè venv đang dùng được;
- **bắt buộc Python 3.10 cho venv chính** (3.11 chấp nhận kèm cảnh báo). Venv
  mới được tạo từ `python3.10` → `/opt/homebrew/bin/python3.10` →
  `/usr/local/bin/python3.10` → `python3.11`; không bao giờ âm thầm rơi về
  `python3` mới hơn (3.12–3.14 không cài được `paddlepaddle`/`Pillow 10.2.0`).
  Không có Python phù hợp thì script dừng với hướng dẫn
  `brew install python@3.10` — không tạo venv hỏng. Nếu `./.venv` có sẵn nhưng
  dùng Python không hỗ trợ, tạo lại bằng `scripts/setup.sh --reset-venv`
  (venv nằm ngoài repo thì không bao giờ tự xoá — bạn tự xoá);
- cài `requirements.txt` — **fail-fast**: pip lỗi là dừng ngay, không được chạy
  các bước sau;
- kiểm tra các import cốt lõi (flask, PIL, yaml, torch, transformers, vietocr,
  argostranslate, sentence_transformers) trước khi báo "Setup complete";
- tạo `.env` từ `.env.example` nếu bạn chưa có;
- tạo các thư mục runtime `logs/`, `uploads/`, `artifacts/`.

> Venv GLM là riêng biệt: `scripts/setup_glm.sh` chấp nhận Python 3.10–3.12 cho
> `GLM-OCR/.venv-mlx` / `.venv-sdk`. **Không** dùng Python 3.14 ở bất cứ đâu.

## 2. Kiểm tra môi trường

```bash
scripts/check.sh
```

Báo cáo Python + venv, các thư viện quan trọng, trạng thái cổng web và GLM, và
tình trạng "sức khoẻ" của SmartDocs cùng (tuỳ chọn) máy chủ GLM. Script này
không thay đổi gì và không báo lỗi chỉ vì GLM đang tắt.

Để kiểm tra **mức sẵn sàng mô hình AI / offline** (chat, viết lại, config+weights
VietOCR, Argos, layout GLM), chạy công cụ chẩn đoán đi kèm:

```bash
scripts/check_offline.sh
```

Nó in ra, theo từng tính năng: dùng được ngay, cần cài online một lần, hay đang
chạy bằng fallback tích hợp.

## 2b. Mô hình AI offline (một lần, cần mạng)

Với `OFFLINE=1` (mặc định), mô hình AI chỉ nạp từ cache cục bộ. Ứng dụng web,
đăng nhập, tải lên, quản lý tài liệu và sửa lỗi cơ bản chạy được ngay, nhưng
**chat, viết lại AI, VietOCR, dịch offline và GLM OCR** cần được chuẩn bị một lần
khi có mạng. Chạy wrapper (tự tìm Python của venv chính):

```bash
scripts/setup_offline.sh                    # luôn dùng Python của venv chính
```

Lệnh này cache: **mô hình LLM cục bộ mặc định Qwen 2.5 1.5B** (dùng cho chat, viết
lại AI và agent), PhoBERT, mô hình embedding RAG, mô hình PaddleOCR, weights VietOCR
**và** `models/vietocr/config.yml`, cùng các gói dịch Argos. Các mô hình lớn hơn
(vd 3B) chỉ tải khi bạn tự bật qua `.env`.
Hướng dẫn đầy đủ: **[OFFLINE_SETUP_VI.md](OFFLINE_SETUP_VI.md)**.

## 3. Khởi động

### Toàn bộ hệ thống (khuyến nghị)

```bash
scripts/start.sh
```

- Khởi động máy chủ GLM ở chế độ nền **nếu** `ENABLE_GLM=true` và venv MLX có
  sẵn; nếu không sẽ in cảnh báo rõ ràng và **vẫn tiếp tục** chạy mà không cần GLM.
- Khởi động ứng dụng web ở chế độ tiền cảnh. Nhấn **Ctrl-C** để dừng web (và cả
  GLM, nếu lệnh này đã khởi động nó).

Mở **http://localhost:5002** (hoặc `SMARTDOCS_PORT` của bạn) và đăng nhập.

### Từng dịch vụ riêng lẻ

```bash
scripts/start_web.sh        # chỉ ứng dụng web (tiền cảnh)
scripts/start_web.sh -b     # chỉ ứng dụng web (chạy nền -> logs/web.log)

scripts/start_glm.sh        # chỉ máy chủ GLM (tiền cảnh)
scripts/start_glm.sh -b     # chỉ máy chủ GLM (chạy nền -> logs/glm.log)
```

## 4. Dừng

```bash
scripts/stop.sh             # dừng web + GLM chạy nền (chỉ tiến trình do script khởi động)
scripts/stop.sh web         # chỉ dừng web
scripts/stop.sh glm         # chỉ dừng GLM
scripts/stop.sh --force     # dừng luôn tiến trình đang giữ cổng (dùng cẩn thận)
```

Mặc định `stop.sh` chỉ dừng tiến trình do chính script khởi động (theo dõi qua
file PID trong `logs/`). Nó **không** giết một tiến trình lạ chỉ vì tiến trình đó
đang giữ cổng — quan trọng trên máy dùng chung. Dùng `--force` để dừng cả tiến
trình cũ/không được theo dõi trên cổng. Dịch vụ chạy tiền cảnh (không có `-b`)
thì dừng bằng **Ctrl-C**.

---

## Cấu hình (`.env`)

Sao chép `.env.example` thành `.env` rồi chỉnh sửa. Các tham số runtime mà
script sử dụng:

| Biến             | Mặc định                         | Ý nghĩa                                              |
|------------------|----------------------------------|-----------------------------------------------------|
| `SMARTDOCS_PORT` | `5002`                           | Cổng web (script ánh xạ sang biến `PORT` của app).  |
| `GLM_PORT`       | `8080`                           | Cổng máy chủ mô hình GLM.                            |
| `GLM_MODEL`      | `mlx-community/GLM-OCR-bf16`     | Nhãn mô hình dùng cho kiểm tra sức khoẻ.            |
| `ENABLE_GLM`     | `true`                           | `start.sh` có cố khởi động GLM hay không.            |

Mọi biến khác trong `.env` (mô hình, thiết bị, API key, chế độ offline) được app
đọc trực tiếp — xem chú thích trong `.env.example`.

---

## Kiểm thử khi CÓ và KHÔNG có GLM

**Không có GLM** (mọi máy, kể cả không phải Mac):

```bash
ENABLE_GLM=false scripts/start.sh
```

App khởi động bình thường. Trong giao diện, Legacy PaddleOCR, PaddleOCR Modern và
VietOCR đều chạy được. Khi chọn engine **GLM OCR** sẽ hiện thông báo lỗi rõ ràng
yêu cầu bật máy chủ GLM — không có gì bị sập.

**Có GLM** (chỉ Apple Silicon) — cài đặt kiểu clean-clone, không dùng đường dẫn ngoài:

```bash
scripts/setup.sh                        # venv SmartDocs chính (giữ Pillow 10.2.0 cho VietOCR)
scripts/setup_glm.sh --precache-layout  # tạo CẢ HAI venv GLM (Py 3.10–3.12) + mlx_config.yaml:
                                        #   .venv-mlx  (máy chủ MLX, từ glm-mlx-lock.txt)
                                        #   .venv-sdk  (glmocr CLI + torch, từ glm-sdk-lock.txt)
                                        # ghi pipeline.layout.model_dir và cache PP-DocLayoutV3
scripts/check.sh                        # kỳ vọng ".venv-mlx imports: OK" và ".venv-sdk imports: OK"
scripts/check_offline.sh                # kỳ vọng "GLM layout config: OK" + mô hình layout đã cache
scripts/start_glm.sh -b                 # bật máy chủ mô hình (lần đầu sẽ nạp mô hình)
scripts/start.sh                        # bật cả stack; sau đó kỳ vọng "GLM health: 200"
```

Chế độ self-hosted của `glmocr` **bắt buộc** có `pipeline.layout.model_dir`.
`setup_glm.sh` ghi giá trị này vào `mlx_config.yaml` (mặc định
`PaddlePaddle/PP-DocLayoutV3_safetensors`, đổi qua `GLM_LAYOUT_MODEL_DIR`).
`--precache-layout` tải checkpoint đó vào HF cache **mặc định** — nơi
`glm_adapter.py` tìm — để chạy được offline. Nếu thiếu, GLM OCR báo lỗi
*"pipeline.layout.model_dir is required for self-hosted layout detection"*.

**Vì sao có ba môi trường Python riêng.** Giao diện SmartDocs **không** import
GLM-OCR trong cùng tiến trình. `services/ocr_engines/glm_adapter.py` chạy
`glmocr.cli` như một **tiến trình con** dùng `GLM-OCR/.venv-sdk/bin/python`
(do `config.py` phân giải, ưu tiên `.venv-sdk` rồi `.venv-mlx`). Nhờ đó ba môi
trường tách biệt:

| Môi trường | Vai trò | Pillow |
|---|---|---|
| venv SmartDocs chính | Flask + Legacy/VietOCR/Modern OCR | **10.2.0** (VietOCR ghim) |
| `GLM-OCR/.venv-mlx` | máy chủ mô hình MLX (`mlx_vlm`) — không torch, không glmocr | 12.x |
| `GLM-OCR/.venv-sdk` | glmocr CLI / layout detector (torch + glmocr editable) | 12.x |

Vì Pillow 12.x của glmocr chỉ nằm trong `.venv-sdk`, nó không bao giờ xung đột
với `Pillow==10.2.0` của VietOCR ở venv chính. `setup_glm.sh` yêu cầu Python
3.10/3.11/3.12 (từ chối 3.13/3.14 trừ khi truyền `--force`).

Phân giải đường dẫn GLM mặc định nằm trong repo:

- `GLM_OCR_DIR` mặc định là `<repo>/GLM-OCR` (bản vendored).
- Trình thông dịch GLM là cái đầu tiên tồn tại trong
  `<repo>/GLM-OCR/.venv-mlx/bin/python` hoặc `.../.venv-sdk/bin/python`.
- Nếu muốn dùng bản GLM-OCR **bên ngoài**, đặt `GLM_OCR_DIR=/đường/dẫn/của/bạn`
  (và tuỳ chọn `GLM_SDK_PYTHON` / `GLM_MLX_PYTHON`) trong `.env`. Không có đường
  dẫn nào bị hardcode theo máy cụ thể.

Sau đó trong giao diện: tab OCR → tải ảnh lên → chọn **🧠 GLM OCR (Structured)** →
Run OCR.

---

## Xử lý sự cố

- **`UNSUPPORTED Python …` / `No matching distribution found for paddlepaddle`** —
  venv được tạo bằng Python 3.12/3.13/3.14. Cài 3.10
  (`brew install python@3.10`) rồi tạo lại: `scripts/setup.sh --reset-venv`.
- **`Main venv is incomplete (missing imports: …)`** — `pip install` chưa hoàn
  tất (hoặc chạy nhầm Python). Chạy lại `scripts/setup.sh` với Python 3.10 và
  đảm bảo kết thúc bằng "Setup complete".
- **`Flask is not installed`** — chạy `scripts/setup.sh`.
- **`Port 5002 already in use`** — SmartDocs đang chạy rồi; dùng `scripts/stop.sh`
  hoặc đặt `SMARTDOCS_PORT` khác.
- **GLM health không phải 200** — kiểm tra `scripts/start_glm.sh` còn chạy và mô
  hình đã nạp xong (xem `logs/glm.log`). GLM chỉ chạy trên Apple Silicon.
- **Nhật ký (logs)** — dịch vụ chạy nền ghi vào `logs/web.log` và `logs/glm.log`.
