# Cài đặt Offline / Clean-Clone (Tiếng Việt)

SmartDocs-Agent theo hướng **offline-first**: với `OFFLINE=1` (mặc định), mọi mô
hình AI chỉ nạp từ cache cục bộ — **không tải gì lúc chạy**. Do đó một bản clone
mới phải được **chuẩn bị một lần khi có mạng** thì các tính năng AI mới hoạt động.
Tài liệu này liệt kê chính xác mỗi tính năng cần mô hình nào, cách tải, và cách
kiểm tra mức sẵn sàng.

> Ứng dụng web, đăng nhập, tải lên, quản lý tài liệu và **sửa lỗi văn bản cơ bản**
> chạy được ngay, không cần tải mô hình. Phần dưới đây nói về các tính năng AI
> (các engine OCR ngoài Paddle, chat, viết lại, dịch, GLM).

---

## Tóm tắt — chuẩn bị một lần cho bản clone sạch

```bash
scripts/setup.sh                        # venv chính + deps + .env + thư mục
scripts/setup_offline.sh                # tải TẤT CẢ mô hình offline (cần mạng, một lần)
scripts/setup_glm.sh --precache         # (chỉ Apple Silicon) venv GLM + mô hình layout + mô hình máy chủ MLX
scripts/check_offline.sh                # kiểm tra: dùng được / cần cài / đang dùng fallback
scripts/start.sh                        # chạy hệ thống
```

> **Luôn dùng `scripts/setup_offline.sh`, không dùng `python tools/setup_offline.py`.**
> Lệnh `python` trần thường trỏ tới Python HỆ THỐNG — không có dependency nào của
> ứng dụng — nên các bước tải thuần vẫn "thành công" nhưng VietOCR `config.yml`,
> Argos và embeddings bị bỏ qua âm thầm với lỗi `No module named 'vietocr' /
> 'PIL' / …`. Wrapper này tìm venv chính của SmartDocs đúng như `scripts/check.sh`
> (`$SMARTDOCS_PYTHON` → `<repo>/.venv` → `<repo>/../.venv`) và từ chối chạy với
> interpreter khác. Bản thân `tools/setup_offline.py` cũng in ra Python đang dùng
> và kết quả import `PIL` / `vietocr` / `argostranslate` / `sentence_transformers`
> — cảnh báo rõ nếu interpreter có vẻ sai. Cả bốn gói đều nằm trong
> `requirements.txt` của venv chính.

---

## Mỗi tính năng cần gì

| Tính năng | Cần (cục bộ) | Được tải bởi | Nếu thiếu → |
|---|---|---|---|
| Paddle OCR Legacy / Modern | cache mô hình PaddleX tại `~/.paddlex/official_models/` (đổi qua `PADDLE_PDX_CACHE_HOME`) | `setup_offline.py` (pipeline Legacy/VietOCR; Modern qua `tools/warmup_modern_models.py`) hoặc lần OCR đầu có mạng | ⚠️ tải ở lần chạy đầu (cần mạng một lần) |
| **VietOCR** | `models/vietocr/config.yml` **+** `vgg_transformer.pth` | `setup_offline.py` | OCR trả lỗi rõ ràng "chạy setup_offline" |
| **GLM OCR** | `.venv-sdk` + `mlx_config.yaml` (`pipeline.layout.model_dir`) + PP-DocLayoutV3 **và** `mlx-community/GLM-OCR-bf16` trong `models/huggingface/hub/` + máy chủ MLX | `setup_glm.sh --precache` (= `--precache-layout` + `--precache-mlx`) | lỗi "pipeline.layout.model_dir is required" / thông báo server chưa chạy / lần khởi động đầu phải tải mô hình máy chủ |
| **AI Chat / AI Rewrite / Agent** | LLM cục bộ **Qwen 2.5 1.5B** (mặc định, `CHAT_MODEL` = `QWEN_MODEL` = `FALLBACK_CHAT_MODEL`) | `setup_offline.py` | "No chat model could be loaded" |
| Tóm tắt PhoBERT | `vinai/phobert-base-v2` | `setup_offline.py` | **fallback** sang TF-IDF trích xuất (vẫn chạy) |
| Embeddings RAG | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | `setup_offline.py` | **fallback** sang truy hồi char-hash (vẫn chạy) |
| **Dịch offline** | gói Argos trong `models/argos/packages/` | `setup_offline.py` | vẫn dịch online bằng Google |

Lưu ý:

- **LLM cục bộ mặc định = Qwen 2.5 1.5B-Instruct.** Chat, viết lại AI và provider
  cục bộ của agent đều dùng nó, nên `setup_offline.py` chỉ tải **một lần**. Các mô
  hình lớn hơn (vd 3B) **không** phải mặc định và **không** được tải trừ khi bạn đặt
  `CHAT_MODEL`/`QWEN_MODEL` trong `.env` — 3B là tuỳ chọn, tự bật. Thiếu 3B **không**
  khiến chat/rewrite báo hỏng.
- **Mô hình layout GLM nằm trong HF cache CỤC BỘ CỦA DỰ ÁN** (`models/huggingface/hub/`),
  cùng chỗ với mọi mô hình khác. `glm_adapter.py` truyền cache này cho tiến trình
  `glmocr`, nên `setup_glm.sh --precache-layout` cache checkpoint vào đó (bản đã có
  trong `~/.cache/huggingface` từ phiên bản cũ sẽ được di chuyển, không tải lại);
  sau đó chạy được với `HF_HUB_OFFLINE=1`. Mô hình chỉ có trong cache toàn cục vẫn
  chạy (fallback tương thích cũ) nhưng `check_offline.sh` sẽ nhắc chạy lại precache.
- **Mô hình máy chủ MLX của GLM (`mlx-community/GLM-OCR-bf16`) cũng nằm trong dự án.**
  `tools/glm_serve.sh` xuất cache hub của dự án trước khi khởi động `mlx_vlm.server`
  và **nạp trước (preload)** mô hình ngay lúc khởi động — cổng chỉ mở khi suy luận
  đã thực sự sẵn sàng, nên "cổng đang lắng nghe" là tín hiệu sẵn sàng đáng tin. Tải
  trước khi có mạng bằng `setup_glm.sh --precache-mlx` (bản đã có trong
  `~/.cache/huggingface` sẽ được di chuyển, không tải lại); nếu chưa precache, lần
  khởi động máy chủ **đầu tiên** sẽ tải mô hình (cần mạng một lần). Khi máy chủ còn
  đang nạp mô hình, GLM OCR trên UI trả lời *"GLM server is still loading the OCR
  model. Please wait and retry."* thay vì lỗi kết nối khó hiểu, và `scripts/check.sh`
  báo "GLM server starting/loading model". Đặt `GLM_PRELOAD=false` để quay về chế
  độ nạp trễ (lazy).

---

## Cấu hình layout GLM self-hosted

Chế độ self-hosted của `glmocr` **bắt buộc** có `pipeline.layout.model_dir`.
`setup_glm.sh` ghi giá trị này vào `GLM-OCR/mlx_config.yaml`:

```yaml
pipeline:
  maas: { enabled: false }
  ocr_api: { api_host: localhost, api_port: 8080, model: mlx-community/GLM-OCR-bf16, api_mode: openai, verify_ssl: false }
  layout:
    model_dir: PaddlePaddle/PP-DocLayoutV3_safetensors   # HF id hoặc thư mục cục bộ
    device: cpu
```

- Đổi checkpoint qua `GLM_LAYOUT_MODEL_DIR` trong `.env` (HF id hoặc đường dẫn tuyệt đối).
- Nếu `mlx_config.yaml` **cũ** (tạo trước bản sửa này) thiếu `layout.model_dir`,
  `setup_glm.sh` sẽ tạo lại (sao lưu bản cũ thành `mlx_config.yaml.bak`).

---

## Kiểm tra mức sẵn sàng

```bash
scripts/check_offline.sh
```

Báo cáo theo từng tính năng: **dùng được ngay**, **cần cài online**, hoặc **đang
dùng fallback** — cùng Python/Pillow chính, config/weights VietOCR, cache Paddle,
cả hai venv GLM, giá trị `pipeline.layout.model_dir`, và **hai dòng riêng cho hai mô
hình GLM** (bộ dò layout PP-DocLayoutV3 và mô hình máy chủ MLX), mỗi dòng kiểm tra
trong hub cục bộ của dự án. Script không thay đổi gì — trạng thái máy chủ GLM được
thăm dò qua `GET /health` (không bao giờ gửi request khiến mô hình bị nạp).

`scripts/check.sh` lo phần runtime/venv và trỏ sang đây cho ma trận mô hình.

Bản kiểm tra **nhận biết tính đầy đủ**: một mô hình chỉ được coi là sẵn sàng khi có
snapshot HF hoàn chỉnh (config + weights) trong cache **cục bộ của dự án**
(`models/huggingface/hub/`) — tải dở hoặc bị hủy giữa chừng sẽ báo **thiếu**, không phải
✅, nên kết quả kiểm tra luôn khớp với những gì ứng dụng thực sự nạp được. Mô hình chỉ
nằm trong cache toàn cục `~/.cache/huggingface` KHÔNG được tính — ứng dụng không bao
giờ nạp từ đó. (Bao gồm cả hai mô hình GLM; bản chỉ có trong cache toàn cục sẽ được
báo là cần chạy `scripts/setup_glm.sh --precache-layout` / `--precache-mlx`.)

---

## Khắc phục sự cố

- **GLM OCR lỗi `Failed to connect to API server at http://localhost:8080/v1/chat/completions within 30 seconds`**
  trong khi `logs/glm.log` hiện `Loading model from: mlx-community/GLM-OCR-bf16` /
  `Fetching 9 files: …%` — máy chủ MLX đang **khởi động nguội**: cổng đã lắng nghe
  nhưng mô hình vẫn đang nạp (hoặc đang tải lần đầu), và cửa sổ kết nối 30 giây của
  SDK glmocr hết hạn. Đã sửa ở ba tầng: `tools/glm_serve.sh` giờ **preload** mô hình
  lúc khởi động (cổng chỉ mở khi suy luận sẵn sàng), UI trả lời *"GLM server is
  still loading the OCR model. Please wait and retry."* thay cho lỗi thô đó, và
  `scripts/check.sh` báo "GLM server starting/loading model; wait or check
  logs/glm.log". Tránh hẳn việc tải lúc khởi động nguội bằng cách precache một lần
  khi có mạng:
  ```bash
  scripts/setup_glm.sh --precache-mlx
  ```
- **Mô hình bị tải vào `~/.cache/huggingface` thay vì `models/`** (ứng dụng báo
  thiếu mô hình dù `setup_offline` "thành công") — đây là lỗi lệch cache: các thư
  viện HF chốt đường dẫn cache ngay lúc import, và một import chạy trước bước
  chuyển hướng cache cục bộ. Đã sửa: `setup_offline.py` giờ ép
  `HF_HOME`/`HF_HUB_CACHE` về `models/huggingface(/hub)` TRƯỚC mọi import HF, tải
  với `cache_dir` tường minh, và **[7/7] xác thực** từng mô hình bằng
  `local_files_only=True` từ cache dự án — không bao giờ in `OFFLINE-READY` khi
  bước xác thực này chưa đạt. Chỉ cần chạy lại:
  ```bash
  scripts/setup_offline.sh
  ```
  Mô hình đã hoàn chỉnh trong cache toàn cục sẽ được **sao chép** tự động vào
  `models/huggingface/hub/` (giữ nguyên snapshots/blobs/refs) — không tải lại.
  Cả hai mô hình GLM giờ cũng nằm trong dự án (`setup_glm.sh --precache`
  di chuyển tương tự), nên khi `scripts/check_offline.sh` đã xanh hết,
  `~/.cache/huggingface` không còn cần cho SmartDocs và có thể xoá toàn bộ.
- **`UNSUPPORTED Python …` / `Main venv is incomplete (missing imports: …)`** —
  `setup_offline.sh` giờ từ chối tải mô hình khi môi trường hỏng. Venv chính
  BẮT BUỘC **Python 3.10** (3.11 chấp nhận); 3.12–3.14 hoàn toàn không cài được
  `paddlepaddle`/`Pillow 10.2.0`. Sửa venv trước:
  ```bash
  brew install python@3.10          # macOS, nếu chưa có 3.10
  scripts/setup.sh --reset-venv     # tạo lại ./.venv bằng Python hỗ trợ
  scripts/setup_offline.sh          # rồi mới tải mô hình
  ```
  Đây là lỗi **môi trường**, không phải lỗi thiếu mô hình — các dòng báo lỗi
  từng mô hình vô nghĩa cho tới khi venv hoàn chỉnh.
- **Cài đặt in ra `No module named 'vietocr' / 'PIL' / 'argostranslate' / 'sentence_transformers'`** —
  bạn đã chạy tool bằng Python sai (hệ thống). Hãy dùng wrapper:
  ```bash
  scripts/setup_offline.sh
  ```
- **`check_offline.sh` báo thiếu mô hình bắt buộc ngay sau khi cài** — quá trình tải
  bị gián đoạn (hoặc một sự cố crash làm `setup_offline.py` dừng giữa chừng). Chỉ cần
  chạy lại; các phần đã xong sẽ được bỏ qua:
  ```bash
  scripts/setup_offline.sh
  ```
  `setup_offline.py` chạy bước PaddleOCR (dễ crash) **sau cùng**, nên VietOCR, Argos
  và các mô hình Qwen/PhoBERT/embedding đã nằm trên đĩa ngay cả khi Paddle gặp lỗi.
- **"No chat model could be loaded" dù trước đó báo ✅** — đó là bản kiểm tra cũ chỉ
  xét sự tồn tại thư mục. Cập nhật lại mã, chạy lại `check_offline.sh`; nếu giờ báo
  thiếu Local LLM, chạy `setup_offline.py`.
- **VietOCR lỗi `'NoneType' object is not iterable`** — triệu chứng cũ của file
  `models/vietocr/config.yml` **rỗng hoặc hỏng** (loader của vietocr crash như vậy
  khi file parse ra rỗng). `scripts/setup_offline.sh` giờ kiểm tra config.yml hiện
  có và **tạo lại** khi hỏng (backup: `config.yml.bak`) bằng chính
  `Cfg.load_config_from_name()` của vietocr, rồi xác nhận bằng cách khởi tạo
  Predictor thật. Runtime và `check_offline.sh` cũng kiểm tra nội dung — file hỏng
  sẽ báo lý do chính xác, không bao giờ ✅.
- **"Offline translation … not installed" dù gói có trên đĩa** — lỗi và
  `/api/translate/status` giờ nêu rõ cặp ngôn ngữ thiếu, các cặp đã cài, và thư mục
  gói (`models/argos/packages`). Nếu gói có trên đĩa nhưng argostranslate không nạp
  được, status sẽ nói rõ điều đó — khởi động lại app và xem server log để biết lỗi
  gốc.
- **Thiếu dịch offline Argos / một cặp không cài được** — mỗi cặp cài độc lập nên các
  cặp khác vẫn thành công. Cài thủ công cặp lõi:
  ```bash
  argospm install translate-en_vi
  argospm install translate-vi_en
  # …hoặc bỏ file .argosmodel vào models/argos/packages/
  ```
  Dịch Google online vẫn hoạt động bình thường.

---

## Sau khi đã chuẩn bị: chạy hoàn toàn offline

Sau khi đã tải, giữ `OFFLINE=1` trong `.env`. Ứng dụng chỉ nạp mô hình
HuggingFace / Argos / Stanza từ `MODEL_DIR`, không chạm mạng. Sao chép toàn bộ thư
mục dự án (kèm `models/` — cả hai mô hình GLM, bộ dò layout và mô hình máy chủ MLX,
giờ cũng ở trong đó) sang máy air-gapped để chạy không cần mạng; chỉ cache PaddleX
(`~/.paddlex/official_models`) nằm ngoài thư mục dự án.
