# SmartDocs-Agent Runtime Context

Current working local run flow on MacBook:

## Terminal 1 — GLM OCR model server

/Users/imtoiteu/Desktop/OCRSoftware/SmartDocs-Agent/tools/glm_serve.sh

## Terminal 2 — SmartDocs web app

/Users/imtoiteu/Desktop/OCRSoftware/.venv/bin/python \
 /Users/imtoiteu/Desktop/OCRSoftware/SmartDocs-Agent/app.py

## Open

http://localhost:5002

## GLM health check

curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/chat/completions \
-X POST \
-H "Content-Type: application/json" \
-d '{"model":"mlx-community/GLM-OCR-bf16","messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}],"max_tokens":3}'

Expected: 200

## Notes

- GLM OCR server is optional.
- Legacy/VietOCR/Modern engines should work without the GLM server.
- If GLM is down, only GLM OCR should show a clear error.
- Current goal is not full desktop packaging yet.
- Current goal is to clean runtime scripts, documentation, env handling, and prepare for desktop wrapper later.

# Collected Local Environment Info

## Date
Sat Jul  4 11:17:57 +07 2026

## macOS
ProductName:		macOS
ProductVersion:		14.6
BuildVersion:		23G80

## Project path
/Users/imtoiteu/Desktop/OCRSoftware/SmartDocs-Agent

## Venv path
/Users/imtoiteu/Desktop/OCRSoftware/.venv

## Python system
/opt/homebrew/bin/python3
Python 3.14.0

## Python venv
Python 3.10.17
/Users/imtoiteu/Desktop/OCRSoftware/.venv/bin/python

## Pip freeze from current venv
accelerate==1.13.0
aiohappyeyeballs==2.6.1
aiohttp==3.13.5
aiosignal==1.4.0
aistudio-sdk==0.3.8
albucore==0.0.24
albumentations==1.4.2
annotated-doc==0.0.4
annotated-types==0.7.0
anyio==4.13.0
argostranslate==1.11.0
async-timeout==4.0.3
attrs==26.1.0
autocorrect==2.6.1
bce-python-sdk==0.9.70
beautifulsoup4==4.14.3
blinker==1.9.0
blis==1.3.3
breadability==0.1.20
cachetools==7.0.6
cairocffi==1.7.1
CairoSVG==2.9.0
catalogue==2.0.10
certifi==2026.2.25
cffi==2.0.0
chardet==7.4.3
charset-normalizer==3.4.7
click==8.3.2
cloudpathlib==0.23.0
coloredlogs==15.0.1
colorlog==6.10.1
confection==1.3.3
contourpy==1.3.2
crc32c==2.8
cryptography==47.0.0
cssselect==1.4.0
cssselect2==0.9.0
cssutils==2.14.0
ctranslate2==4.7.1
cycler==0.12.1
cymem==2.0.13
Cython==3.2.4
dataclasses-json==0.6.7
deep-translator==1.11.4
defusedxml==0.7.1
distro==1.9.0
docopt==0.6.2
docopt-ng==0.9.0
einops==0.2.0
emoji==2.15.0
encutils==1.0.0
et_xmlfile==2.0.0
exceptiongroup==1.3.1
faiss-cpu==1.13.2
filelock==3.29.0
Flask==3.1.3
Flask-Login==0.6.3
Flask-SQLAlchemy==3.1.1
flatbuffers==25.12.19
fonttools==4.62.1
frozenlist==1.8.0
fsspec==2026.3.0
ftfy==6.3.1
future==1.0.0
gdown==4.4.0
h11==0.16.0
hf-xet==1.4.3
httpcore==1.0.9
httpx==0.28.1
httpx-sse==0.4.3
huggingface_hub==1.11.0
humanfriendly==10.0
idna==3.12
ImageIO==2.37.3
imagesize==2.0.0
imgaug==0.4.0
iopath==0.1.10
itsdangerous==2.2.0
Jinja2==3.1.6
jiter==0.14.0
joblib==1.5.3
jsonpatch==1.33
jsonpointer==3.1.1
kiwisolver==1.5.0
langchain==0.3.28
langchain-community==0.3.31
langchain-core==0.3.84
langchain-openai==0.3.35
langchain-text-splitters==0.3.11
langdetect==1.0.9
langsmith==0.7.33
latex2mathml==3.81.0
layoutparser==0.3.4
lazy-loader==0.5
lmdb==2.2.0
lxml==6.1.0
lxml_html_clean==0.4.4
markdown-it-py==4.0.0
MarkupSafe==3.0.3
marshmallow==3.26.2
matplotlib==3.10.9
mdurl==0.1.2
minisbd==0.9.5
modelscope==1.36.1
more-itertools==11.0.2
mpmath==1.3.0
multidict==6.7.1
murmurhash==1.0.15
mypy_extensions==1.1.0
networkx==3.4.2
nltk==3.9.4
numpy==2.2.6
onnxruntime==1.23.2
openai==2.32.0
opencv-contrib-python==4.10.0.84
opencv-python==4.13.0.92
opencv-python-headless==4.13.0.92
openpyxl==3.1.5
opt-einsum==3.3.0
orjson==3.11.8
packaging==25.0
paddleocr==3.7.0
paddlepaddle==3.3.1
paddlex==3.7.1
pandas==2.3.3
pdf2image==1.17.0
pdfminer.six==20251230
pdfplumber==0.11.9
pillow==10.2.0
portalocker==3.2.0
prefetch_generator==1.0.1
premailer==3.10.0
preshed==3.0.13
prettytable==3.17.0
propcache==0.4.1
protobuf==7.34.1
psutil==7.2.2
py-cpuinfo==9.0.0
pyclipper==1.4.0
pycountry==26.2.16
pycparser==3.0
pycryptodome==3.23.0
pydantic==2.13.3
pydantic-settings==2.14.0
pydantic_core==2.46.3
Pygments==2.20.0
pyparsing==3.3.2
pypdfium2==5.7.1
PySocks==1.7.1
python-bidi==0.6.7
python-dateutil==2.9.0.post0
python-docx==1.2.0
python-dotenv==1.2.2
python-pptx==1.0.2
pytz==2026.1.post1
PyYAML==6.0.2
RapidFuzz==3.14.5
regex==2026.4.4
requests==2.33.1
requests-toolbelt==1.0.0
rich==15.0.0
ruamel.yaml==0.19.1
sacremoses==0.1.1
safetensors==0.7.0
scikit-image==0.25.2
scikit-learn==1.7.2
scipy==1.15.3
sentence-transformers==5.4.1
sentencepiece==0.2.1
shapely==2.1.2
shellingham==1.5.4
simsimd==6.5.16
six==1.17.0
smart_open==7.6.0
sniffio==1.3.1
soupsieve==2.8.3
spacy==3.8.14
spacy-legacy==3.0.12
spacy-loggers==1.0.5
SQLAlchemy==2.0.49
srsly==2.5.3
stanza==1.10.1
stringzilla==4.6.0
sumy==0.12.0
sympy==1.14.0
tenacity==9.1.4
thinc==8.3.13
threadpoolctl==3.6.0
tifffile==2025.5.10
tiktoken==0.12.0
tinycss2==1.5.1
tokenizers==0.22.2
tomli==2.4.1
torch==2.11.0
torchvision==0.26.0
tqdm==4.67.3
transformers==5.6.0
typer==0.24.1
typing-inspect==0.9.0
typing-inspection==0.4.2
typing_extensions==4.15.0
tzdata==2026.1
ujson==5.12.0
underthesea==9.4.0
underthesea_core==3.3.0
urllib3==2.6.3
uuid_utils==0.14.1
vietocr==0.3.13
wasabi==1.1.3
wcwidth==0.6.0
weasel==1.0.0
webencodings==0.5.1
Werkzeug==3.1.8
wrapt==2.1.2
xlsxwriter==3.2.9
xxhash==3.6.0
yarl==1.23.0
zstandard==0.25.0

## Git status
 M run.md
?? RUN_CONTEXT_FOR_CLAUDE.md

## Git branch
main

## Top-level files
.
./.DS_Store
./.claude
./.claude/skills
./.env
./.env.example
./.git
./.gitignore
./.gitmodules
./CLAUDE.md
./GLM-OCR
./GLM-OCR/.git
./GLM-OCR/.github
./GLM-OCR/.gitignore
./GLM-OCR/.pre-commit-config.yaml
./GLM-OCR/LICENSE
./GLM-OCR/README.md
./GLM-OCR/README_zh.md
./GLM-OCR/agent.md
./GLM-OCR/apps
./GLM-OCR/examples
./GLM-OCR/glmocr
./GLM-OCR/pyproject.toml
./GLM-OCR/resources
./GLM-OCR/skills
./README.md
./RUN_CONTEXT_FOR_CLAUDE.md
./__pycache__
./admin_bp.py
./agent
./agent/__init__.py
./agent/__pycache__
./agent/core
./agent/knowledge
./agent/memory
./agent/ocr_routing.py
./agent/results.py
./agent/skills
./agent/tests
./agent/tools
./agent_bp.py
./app.py
./auth.py
./chat_bp.py
./config.py
./docs
./docs/.DS_Store
./docs/ARCHITECTURE-DIAGRAMS.md
./docs/ARCHITECTURE.md
./docs/DEPLOYMENT.md
./docs/INSTALLATION.md
./docs/OCR_ENGINES.md
./docs/diagrams
./docs/ocr_panel_before_after.png
./docs/ocr_selector_before_after.png
./models.py
./paddleocr.db
./requirements.txt
./run.md
./run_mac.sh
./run_windows.bat
./services
./services/__init__.py
./services/__pycache__
./services/activity_registry.py
./services/ai_rewrite_service.py
./services/chat_service.py
./services/correction_service.py
./services/cpu_threads.py
./services/geometry_service.py
./services/layout_service.py
./services/llm_registry.py
./services/markdown_normalize.py
./services/ocr_engines
./services/ocr_service.py
./services/smart_ocr_service.py
./services/summary_service.py
./services/text_service.py
./services/translate_service.py
./static
./static/agent.html
./static/agent.js
./static/app.js
./static/chat.css
./static/chat.js
./static/i18n.js
./static/img
./static/index.html
./static/ocr-canvas.js
./static/style.css
./static/vendor
./templates
./templates/403.html
./templates/admin
./templates/login.html
./test_layout.py
./test_markdown_normalize.py
./test_refactored_ocr.py
./test_regression.py
./test_vietocr.py
./tools
./tools/ab_harness.py
./tools/ab_results
./tools/download_chat_model.py
./tools/eval_model.py
./tools/eval_results
./tools/glm_serve.sh
./tools/setup_offline.py
./tools/warmup_modern_models.py
./uploads
./uploads/0004e789-5759-4e64-9a79-8629f36fdd68.jpeg
./uploads/00194c9e-2935-4df5-8853-5ac5bee85889.jpeg
./uploads/02e90dd5-954f-410b-96b0-a1fd651acf20.jpeg
./uploads/037fc3d9-0ad3-472b-9a4d-1db90269e925.jpeg
./uploads/039d719b-9964-44f6-9e91-a6b7cc180e3c.png
./uploads/04c9bac2-2bb0-4f9a-846d-194b3c3ec005.png
./uploads/07160efd-e4ad-49de-9135-ac6c3e71b156.jpeg
./uploads/0903c8a3-79fb-4a8b-b081-c5ac2de50fa6.jpeg
./uploads/0c2ea394-10ba-486c-b184-e13f27b84cdc.jpeg
./uploads/0c93b8a2-cf81-47b8-99d8-9a491322b2a6.jpeg
./uploads/0dd66ce5-80de-43f3-aa53-b8a2f13878dd.jpg
./uploads/0e7dfb86-0126-4820-9775-d66517c2c59c.jpg
./uploads/0ea7fdae-0a4d-47f7-8336-b651cd0733dc.jpeg
./uploads/0fbb4dc1-6f56-43d9-906c-6cd1db402a01.jpeg
./uploads/10731af5-17c2-45ff-936e-9cc7858ae7fc.pdf
./uploads/11d36f32-b88f-4a8d-8032-6b924c4de40a.webp
./uploads/122885e8-08df-4e51-a4b2-fc52099899a6.webp
./uploads/14de1943-f8d7-4e23-813b-c3a2e38b0871.png
./uploads/157740db-18a5-4d82-9de5-56187252e823.jpeg
./uploads/15f98ba2-838c-4193-bb61-f5fe726abbb7.webp
./uploads/188a2fcd-b004-469c-9670-83ca4ae3989e.jpeg
./uploads/189b0617-9f3f-4edb-a551-d7cc56542d30.jpeg
./uploads/1a153b79-cb76-4b16-9dc9-8c6394cbf08e.jpg
./uploads/1abf3a3b-8a58-4048-88ab-9b1648e45db6.jpg
./uploads/1ba93135-6adf-4df6-80de-aae70490e0a4.png
./uploads/1c780b86-67af-4afd-8bc2-e83d3a8b95b4.jpeg
./uploads/1d24b689-890e-413e-becf-3d4c01d58b46.png
./uploads/1ddd2462-2d02-484c-9345-7ca104666761.jpeg
./uploads/2010f049-2481-4804-86a6-8637cefc300b.jpg
./uploads/207d51d3-2291-4bb9-84e0-319b49123ff0.jpeg
./uploads/20c1e5a0-9238-49ae-ac11-aa5d7374c2a2.png
./uploads/2456ca07-0149-44db-8857-8861cd272042.jpg
./uploads/25bf9894-be2c-42c3-ac5c-b2ef0be09f15.jpeg
./uploads/26a3fcd6-10f9-4c75-a2c8-69dd051a57a6.png
./uploads/26a4ac05-3d96-4efd-8c7f-8d678f360069.webp
./uploads/28686dca-0ac4-4fcd-a8fc-a41cb4e001df.png
./uploads/28961701-b39e-4daa-97f3-d437f300f02e.png
./uploads/28bd34f4-acb6-4092-be7a-c675fcde5239.webp
./uploads/28c0f5cc-9604-4eb3-8d5e-9592807fda72.png
./uploads/29d935d3-90ba-47c2-a481-829b5ce7a025.png
./uploads/2a069137-e949-4037-ba86-651bb2536da5.jpeg
./uploads/2af6845c-dcc0-4fd7-9396-bcc45dae7042.docx
./uploads/2b7baf29-3052-484a-8889-613fe24e38ea.jpg
./uploads/2c6c9c7b-8931-4bf5-851d-f7f951475fa7.png
./uploads/2d53929e-861e-4cc1-abfc-153e96b1a8d6.docx
./uploads/30240dc0-017b-42f4-964a-6da56a8119a4.jpeg
./uploads/31486730-dd7c-4fea-b7d8-8766a05c59df.png
./uploads/33b2c447-5027-4b25-b75f-e45eb342b4ee.jpeg
./uploads/343b275a-0627-4082-873a-c1e733de1d83.jpeg
./uploads/3443c28f-5807-4d1e-b35b-7d3433134876.png
./uploads/34a1e545-6cbe-4bcf-b023-b2537ebbc648.pdf
./uploads/34cb44ae-d668-41f8-bd2b-6497f7278baa.webp
./uploads/359335b8-0df6-4301-9fcb-9c05ceff76e2.jpeg
./uploads/35dc10d2-d964-4c20-8989-de13ea582077.jpg
./uploads/396b042f-b252-491f-badd-5fb480a5cf50.jpg
./uploads/398cbd85-129a-4495-b0c7-83d160fbd7a3.jpeg
./uploads/3a53bab0-f011-45cb-8569-d00cd865138a.jpeg
./uploads/3aa4be7d-5a5f-4af7-a090-1088cf739326.webp
./uploads/3c68c2d1-e282-4c58-bf45-35bbaaa53bb4.png
./uploads/3cb32d2e-ed70-45c9-b0b3-5a120b547cbc.jpg
./uploads/3d31bbe4-aa23-407a-821f-3e7bb4175a28.png
./uploads/3e23dcdc-627d-45d2-91ec-28bc2b557ccf.jpeg
./uploads/3f0882fc-84eb-4dfe-a300-644de3ce34ff.png
./uploads/3f7055dd-8d65-4ec5-a850-459b6907152b.png
./uploads/3fa50009-a4c4-4ba3-b173-245eb8f66f5e.pdf
./uploads/3fd6f88c-06f1-49b6-a768-5d88088c505b.docx
./uploads/42fe8da1-68ef-41fc-b0c5-a699e0945a3d.png
./uploads/4357fc1f-35a2-4486-81ec-3db3b9aa82c9.pdf
./uploads/43fbdd97-bc6a-4519-82bf-d25095ee054a.jpeg
./uploads/44158676-48c6-4cbd-8c3f-231df1047f41.png
./uploads/462d4fda-958b-425c-be81-29c1bf0fdcba.jpeg
./uploads/48ff3a4a-c7d4-4cde-ae27-c777bebea29c.jpeg
./uploads/49f26f4d-85a3-4725-814d-b31db917f4fe.jpeg
./uploads/4bb557b2-258f-49a2-a39b-37484f9694f2.jpg
./uploads/4c1c8a12-64b0-4f83-95b5-9695ad411dea.docx
./uploads/4cbb1d7f-3a71-45d8-b0d8-647749cafed5.png
./uploads/4d6fc937-934b-4fdb-9de1-4e3c31fb83bc.jpeg
./uploads/4eba32fa-535e-4449-96fa-8a61ca8f08f9.jpg
./uploads/4eeba20f-1c0d-4fd6-a8c8-51566f514a13.png
./uploads/4fed6fa4-0dce-4ef0-a0bb-a9321548c913.png
./uploads/50db53ce-7e7b-4219-a169-62ae4506716a.jpeg
./uploads/52dde81f-15cc-48f6-bbfe-9f4b5ecb344e.png
./uploads/538c07ce-3d2c-4ff6-aeb3-14b3c5486346.jpg
./uploads/540c308c-d37a-4d6c-bb71-32b1c4f43e20.jpeg
./uploads/580e3359-0b24-48d3-8cd4-acc1b6cb4199.jpeg
./uploads/586eecc8-8bdc-42e4-bd6c-2db6673602b4.jpg
./uploads/58e683bf-bf8d-4efb-9220-de8ac690bfac.jpeg
./uploads/5b710042-2608-4f58-af5d-fbd7a71d547f.jpg
./uploads/5b8e8d8a-2622-42b3-8952-7cf545b6778b.png
./uploads/5b9929c3-ad64-4f63-95e6-0c9107d3a52d.jpeg
./uploads/618f13a5-f8f4-426c-bb35-fae00c85bfb3.png
./uploads/61d09f0c-73b4-4b39-a7a3-a2bf2d2b715f.jpeg
./uploads/638800b0-bb88-4a02-bf34-27614bb44575.jpeg
./uploads/680e3cdd-1713-4974-978c-4d7bc1927fb8.jpg
./uploads/68812913-c348-479a-9f23-88e5a60c4857.jpg
./uploads/69ae7832-4f13-4cea-a500-114584dc5700.webp
./uploads/6cf2104b-e724-463d-9ade-a40494242050.jpg
./uploads/6ecaa5bd-6430-402d-8cbb-3052e85fcccf.png
./uploads/6f036e45-241e-4733-b5cb-fa07f7888aa4.png
./uploads/6f03d7c4-6600-4004-b6fc-a0652d47a13a.jpeg
./uploads/70c69a5a-0e9b-4f3f-8f15-9f5f66282574.webp
./uploads/727512e4-0a32-4834-b3e7-9f5abdb6ce1b.jpg
./uploads/73af7f7e-2794-4511-acec-231184ecf58f.png
./uploads/76a490b9-45d1-410c-bbb9-cd6f15b22265.jpeg
./uploads/77f67a62-c8f9-4d69-b924-aaabf54192db.png
./uploads/78eec1f0-5d89-427f-af44-75b910213227.jpeg
./uploads/791968e6-4693-4c18-a68d-e9c2b48e4473.pdf
./uploads/7ad661a9-8b3a-42fa-a458-491bd1082c4f.pdf
./uploads/7b2e04b8-1c0f-4fa3-83ff-07d16569903c.png
./uploads/7c3e0903-a8e0-492c-b1a6-704acd1334e5.png
./uploads/7de296e4-ccd8-42e0-a261-0adbb0140024.png
./uploads/7ec6a15d-ed2a-4163-8e78-d3c12674bfcb.jpeg
./uploads/7fdbc857-ac5b-4520-8b20-7a09f3affb73.webp
./uploads/80e0e506-4522-4517-8c2e-de21ee8b149c.png
./uploads/825853b6-05a8-445b-85cb-a8c0b7b1c2f4.jpeg
./uploads/83a5f776-95b9-4306-a86d-9f9c603fcc33.jpeg
./uploads/84599369-49f4-45a4-bd73-6590900db353.png
./uploads/8569a8bc-d602-4b0d-8173-4eaae6f0824d.jpeg
./uploads/860ce976-fee6-44a8-b7b3-98fc19670b68.jpeg
./uploads/86418acf-7c48-4d7f-93b6-843f7adca988.png
./uploads/87ee3b34-f0ed-46f1-9f37-8cf73dc328cb.jpg
./uploads/886f2d70-c60d-4b65-92a9-a07fb118ca49.webp
./uploads/890f3bb3-da6d-4857-a276-f3d462b71487.jpg
./uploads/89da816f-8f33-4820-b001-612c4bb21c58.jpg
./uploads/8ad1eeb0-8693-44e6-a24b-265b82efe1de.webp
./uploads/8adbeb9b-d0c9-4177-a29b-53e0945c8e21.jpeg
./uploads/8c40d8e6-474e-477e-95b9-2d0c3e476766.jpeg
./uploads/8ce55641-cc8d-4a33-8434-4091c17113d0.png
./uploads/8ce638d1-c2f0-457c-9a0c-0978d214efae.jpeg
./uploads/8d4a5690-d7c6-4ea6-a1a6-3b33f94441fb.docx
./uploads/8dfc4b52-6ee6-46c1-88eb-281bab5bbdf6.jpeg
./uploads/8e3090b5-65f9-4ad5-a212-a862b9176775.docx
./uploads/8f0c01e9-a08a-4c7c-b8c1-e065509948c6.jpeg
./uploads/90bf37cb-f4af-47d2-9e5a-f80d76a948ac.png
./uploads/911f6155-1d86-4311-85ee-5fed490d14d5.docx
./uploads/91b628f5-5902-4606-a7d1-07c419b7e1ce.jpg
./uploads/91fef525-7e88-4b09-9e04-1c8a09d0d08a.png
./uploads/920bebab-efde-4b52-9b98-b832e972b953.docx
./uploads/921d8a27-f243-43ca-b9bd-51912ef5fb02.png
./uploads/928d6305-3bac-4ac0-8dd5-14623c2faf53.jpeg
./uploads/940b245d-846f-4f3a-bf3f-78c460540296.webp
./uploads/9598816a-6b44-41b3-9402-e359382c9c6d.png
./uploads/987c4373-e74d-407b-add8-891b325b22a0.jpeg
./uploads/993eeba4-9d4b-4764-aeb8-b6170e2bdd7b.jpeg
./uploads/9a41dd31-3394-4620-8b3f-a91ddcf95241.png
./uploads/9e805e02-57a6-4b70-9dce-d4b5331b1c30.png
./uploads/9ec91945-c07a-4017-a3e8-bd0d8bbfb0c2.png
./uploads/9f6b2e6c-a3bb-4429-a4ef-a62ee9bfceea.webp
./uploads/9fc0eb30-2b95-41e5-a359-0b104b567c05.docx
./uploads/a090150b-f94d-4693-bb2f-2a0ba66617bc.pdf
./uploads/a179a4cb-47d9-4562-9fb3-dbe690831e5e.jpeg
./uploads/a19d252e-99b5-4bf9-a789-e1b4a492c1ef.jpg
./uploads/a1dfa5fd-da23-4752-b023-3878b3709142.png
./uploads/a31dccd5-2251-4426-a8b5-795fe5b530fc.png
./uploads/a569542c-6e71-4194-b5a5-71a422f1fa11.jpeg
./uploads/a60b58f8-bef1-41ee-91a4-c03c6d6c88ee.jpeg
./uploads/a632ae4a-23b6-4663-8db0-6fddc1798833.jpeg
./uploads/ac9bec9c-877f-4b62-886a-c043537d1cd2.png
./uploads/ad7c2b96-81dd-4fcc-99d1-a2c9e2411b2f.png
./uploads/aebd4568-396f-4a82-afdb-43042cd07b07.pdf
./uploads/af83717b-135b-4454-b2c2-0038f63811f2.png
./uploads/b07404c8-46f8-4b6f-a254-c5960c9eadcb.jpeg
./uploads/b0ccd954-1360-4592-a5d6-df5d90ff10e9.jpeg
./uploads/b0ff02a6-2bcf-4fd6-ae06-9641a8458550.jpeg
./uploads/b173f93d-ec49-43a0-834d-aab508b6848c.png
./uploads/b293f129-a69d-4b3b-ba13-1d5b68d49b0d.jpg
./uploads/b31172d6-1c73-42ac-a4b3-0b42291a0e9d.pdf
./uploads/b3fdf199-f6e0-40b8-a29a-f3279c103441.png
./uploads/b4d8b1ef-13bd-42cc-8a49-78dac0428bb3.docx
./uploads/b5465ee6-9588-45a8-add7-d6ecd03c10d2.docx
./uploads/b54cf2dc-c7c2-45ae-8b11-c06d1a684b0f.webp
./uploads/b5ab6515-2cfd-4bc4-bcf9-70609ef16903.jpeg
./uploads/b5fdbc91-8708-4908-8aee-0374fa5655bf.jpeg
./uploads/b6fae607-67e6-4c75-9a67-635a22894284.pdf
./uploads/b760d08c-bf84-4516-9f91-01a02d5b43cd.jpeg
./uploads/b765830b-b30c-44c5-b4ff-610428d67608.png
./uploads/b8bafe2c-f1af-4a32-8f54-aa4df357a34c.png
./uploads/bbd23b9c-bf60-4e56-8ceb-af383873ddd8.png
./uploads/be175cd9-1100-4d23-8cb4-bfc45860bcf8.jpg
./uploads/be5275e8-f156-4ac7-b8fa-c58ea19ec693.png
./uploads/bf36247d-33a3-4ca4-aa7c-74cbf7222b31.webp
./uploads/bf7da855-58a8-474e-b087-4dd07e98f790.pdf
./uploads/c2aa0846-4ab1-415b-9903-f150f8ecd626.png
./uploads/c2adc0c3-77ff-454c-b51a-99617f0f607e.jpeg
./uploads/c35fc399-0832-4f1b-b82f-a6bd69b2e57b.png
./uploads/c364534f-0221-4921-b17e-9e4a0e2b5f99.jpeg
./uploads/c400733a-aca7-4844-ab37-b134f5451c2b.jpg
./uploads/c7af5c8e-7539-414c-8b50-4b0e40a200e1.docx
./uploads/c855ddc1-5c2b-45e6-be73-8a36d97ad262.jpeg
./uploads/c901e93e-7216-463b-968b-c86b395c2387.png
./uploads/ca8ad43e-b988-4515-85b3-f2619fec5c86.png
./uploads/cc654660-f69e-403c-a6e2-5697da512b4c.jpg
./uploads/cd9506c3-b861-4837-80da-22dd21f95e1e.png
./uploads/cdd6da96-aeef-4ac7-b27a-f318ae38bb56.jpg
./uploads/ce45e507-47df-4f1a-9be2-45cf17469790.jpg
./uploads/ce59cd0b-1e25-4ce8-bce7-0a803a10ae72.jpeg
./uploads/cf4f10c2-40d7-4d74-84bc-14607820225b.jpeg
./uploads/cfc6dcf6-ca3b-49a1-8238-db638cba4e81.jpeg
./uploads/d0d4f295-5af2-4183-ac8a-de6c206342e8.jpeg
./uploads/d2eb1c24-9458-40d1-9d48-c73ee1071cbc.pdf
./uploads/d336fae6-9509-47de-bfcb-3fa10d8e4adc.webp
./uploads/d7ea34da-2473-467c-b27e-186e25f71e54.png
./uploads/db272ac2-ecd2-4a0f-b544-88b26a9bc430.docx
./uploads/dcaa9d39-aaf8-4dd9-a16a-8681174805ea.jpg
./uploads/dd943abb-7761-47bc-ae01-f2ce8428aff6.jpeg
./uploads/e0648d9f-0c0c-4895-9cea-190fdc183e5d.jpeg
./uploads/e1bee4c7-ff2b-4ae9-86b4-d176facfc0e4.jpeg
./uploads/e1fa0e1c-2b85-406b-8983-6ff29cde078c.jpeg
./uploads/e3bc5b6d-19a8-42c2-8ace-a4341b5dd213.png
./uploads/e5480210-4246-47c3-a77f-ecd7fb7ea26f.docx
./uploads/e63c80e2-281d-4732-8112-6779b5214b9d.jpeg
./uploads/e63dcff2-0050-4f02-9537-2dcad40e61cc.jpg
./uploads/e73d34e7-0cce-452c-80ae-c5219f798a80.jpg
./uploads/eb2653b2-e73a-4bab-aa0e-e798292d1ec0.jpg
./uploads/ec48f930-9b52-433a-be5d-74388add5a94.pdf
./uploads/ee03cc7f-88a5-4b0d-9c82-be1f61a8137b.jpeg
./uploads/ee0a27f9-122e-414e-bb3a-75762c722cfa.jpeg
./uploads/efdb207b-1769-4373-b615-d8a802eae220.png
./uploads/f1dfffd0-04c4-489f-98a9-0b4069783277.jpeg
./uploads/f257982e-98d2-4616-8c17-44aa55fdbc98.jpeg
./uploads/f3ac188f-661e-4eb2-bc08-bcd297d3e9b4.jpg
./uploads/f3dcac55-fd89-434a-b0e5-0e687b54c028.jpeg
./uploads/f4c3dbdc-f0f6-4669-abaf-edfe38afec89.webp
./uploads/f5102247-21bc-44b0-912f-43c62cd6fe3d.webp
./uploads/f5b69e96-64ac-455e-a5c3-4caee173e799.jpeg
./uploads/f968998f-0bb0-4791-a41d-c6069e575fc7.png
./uploads/fa8f07d7-0f92-4830-846c-3e54f5cf7601.pdf
./uploads/fa904044-6d70-422a-90f3-7a2b888f9ed0.jpeg
./uploads/fe1726d0-0475-4a21-9b50-50be2f8b49bf.jpeg
./uploads/fe7d1e03-1eab-409a-9805-6180722ddde7.png
./uploads/tmp4u6nhw1g.png
./uploads/tmpdohhxznu.png
./uploads/tmprcrsqhfw.png

## Size summary
314M	.
