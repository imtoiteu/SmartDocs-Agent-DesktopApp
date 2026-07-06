#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generator for the SmartDocs **DesktopApp** diagram set (Vietnamese labels).

Reuses the layout/render core of build_diagrams.py (same directory) and emits
BOTH <name>.drawio (editable) and <name>.svg (publication) per diagram.

The set reflects the CURRENT DesktopApp design (grounded in
docs/DESKTOP_ARCHITECTURE.md, src-tauri/src/runtime.rs, desktop_gateway.py,
agent/core/model_registry.py + llm_gateway.py, agent_bp.py):

  D1  desktop-overall-architecture      Kiến trúc tổng thể
  D2  desktop-runtime-architecture      Ba chế độ backend runtime
  D3  desktop-deployment                Kiến trúc triển khai
  D4  desktop-runtime-selection-flow    Luồng chọn & khởi động runtime
  D5  desktop-gateway-flow              UI Gateway — luồng xử lý yêu cầu
  D6  desktop-model-routing             Model Registry & Router theo tác vụ
  D7  desktop-privacy-local-only        Local-only · khóa API · chính sách URL
  D8  desktop-document-flow             Vòng đời tài liệu (OCR → chat)
  D9  desktop-agent-flow                Luồng thực thi Agent

Run:  python3 build_desktop_diagrams.py
"""
import os

import build_diagrams as B

OUT = os.path.dirname(os.path.abspath(__file__))


def write(d):
    with open(os.path.join(OUT, d.name + '.drawio'), 'w', encoding='utf-8') as f:
        f.write(B.render_drawio(d))
    with open(os.path.join(OUT, d.name + '.svg'), 'w', encoding='utf-8') as f:
        f.write(B.render_svg(d))
    print('wrote', d.name + '.drawio', '+', d.name + '.svg', '(%dx%d)' % (d.w, d.h))


# ================================================================ D1
def d1_overall():
    d = B.Diagram('desktop-overall-architecture',
                  'D1 · Kiến trúc tổng thể SmartDocs DesktopApp', 1360, 770)
    # ── Tauri shell
    d.container('SHELL', 40, 64, 1280, 100,
                'Tauri Shell (Rust — src-tauri) — cửa sổ gốc, vòng đời tiến trình', 'ext')
    sx = B.row_x(64, 1296, 4, 296)
    d.node('sh1', int(sx[0]), 104, 296, 48, 'Cửa sổ & vòng đời\nmain.rs — spawn / dừng sidecar', 'ext', parent='SHELL', fontsize=11.5)
    d.node('sh2', int(sx[1]), 104, 296, 48, 'Chế độ runtime\nruntime.rs — đọc/ghi runtime.json', 'ext', parent='SHELL', fontsize=11.5)
    d.node('sh3', int(sx[2]), 104, 296, 48, 'Menu gốc: Backend Runtime…\n(Cmd/Ctrl + ,) + khôi phục khi lỗi', 'ext', parent='SHELL', fontsize=11.5)
    d.node('sh4', int(sx[3]), 104, 296, 48, 'Token khởi chạy 64-hex\n(truyền qua stdin — không qua env)', 'ext', parent='SHELL', fontsize=11.5)
    # ── WebView UI
    d.container('UI', 40, 186, 1280, 108,
                'WebView — Giao diện DesktopApp (GIỮ NGUYÊN trong mọi chế độ runtime)', 'fe')
    d.node('sidebar', 64, 226, 560, 52,
           'Sidebar điều hướng\nTrang chủ · OCR · Sửa lỗi · Dịch · Tóm tắt · Tài liệu · SmartDocs AI · Agent · Cài đặt',
           'fe', parent='UI', fontsize=11)
    d.node('settings', 640, 226, 330, 52,
           'Trang Cài đặt\nRuntime · AI models · Quyền riêng tư · Khóa cloud', 'fe', parent='UI', fontsize=11.5)
    d.node('splash', 986, 226, 310, 52,
           'Splash / Trình chọn runtime\n(origin bundled duy nhất được gọi lệnh Tauri)', 'fe', parent='UI', fontsize=11)
    # ── UI gateway
    d.container('GW', 40, 318, 1280, 100,
                'UI Gateway — desktop_gateway.py · origin DUY NHẤT của WebView: http://127.0.0.1:<cổng>', 'agent')
    gx = B.row_x(64, 1296, 3, 396)
    d.node('gw1', int(gx[0]), 358, 396, 48, 'Phục vụ giao diện từ asset DesktopApp\n/ · /agent · /static/*', 'agent', parent='GW', fontsize=11.5)
    d.node('gw2', int(gx[1]), 358, 396, 48, 'Proxy theo allowlist\n/api/* · /login · /logout · /admin', 'agent', parent='GW', fontsize=11.5)
    d.node('gw3', int(gx[2]), 358, 396, 48, 'Trả lời cục bộ\n/api/desktop/health · shutdown (cần token)', 'agent', parent='GW', fontsize=11.5)
    # ── runtime modes
    d.container('RT', 40, 442, 1280, 112,
                'Backend runtime — chọn 1 trong 3 chế độ (runtime.json)', 'be')
    d.node('rt1', int(gx[0]), 482, 396, 56,
           '1 · Bundled Core (mặc định)\nSidecar PyInstaller — Flask đầy đủ chạy trên máy này', 'be', parent='RT', fontsize=11.5)
    d.node('rt2', int(gx[1]), 482, 396, 56,
           '2 · WebApp Runtime\nvenv của bản WebApp đã cài chạy desktop-shim', 'be', parent='RT', fontsize=11.5)
    d.node('rt3', int(gx[2]), 482, 396, 56,
           '3 · Remote Server\nServer SmartDocs từ xa — CHỈ là backend, không phải origin UI', 'be', parent='RT', fontsize=11.5)
    # ── bottom row
    d.container('MODELS', 40, 584, 760, 120, 'Phục vụ mô hình AI (model serving)', 'llm')
    mx = B.row_x(60, 780, 3, 226)
    d.node('m1', int(mx[0]), 626, 226, 58, 'Qwen cục bộ (đóng gói)\nfallback cuối — chạy CPU', 'llm', parent='MODELS', fontsize=11)
    d.node('m2', int(mx[1]), 626, 226, 58, 'Server tự host (OpenAI-compatible)\nOllama · vLLM · llama.cpp · LM Studio', 'llm', parent='MODELS', fontsize=10.5)
    d.node('m3', int(mx[2]), 626, 226, 58, 'Cloud API: Groq · Gemini\n(bị chặn khi bật Local-only)', 'llm', parent='MODELS', fontsize=11)
    d.node('db', 850, 596, 220, 96, 'Dữ liệu ứng dụng\nSQLite · uploads · artifacts\n(app data dir riêng)', 'db', shape='cyl', fontsize=11)
    d.node('keys', 1104, 600, 216, 88, 'Kho khóa hệ điều hành\nKeychain · Credential Manager\n· Secret Service', 'sec', fontsize=11)
    # ── edges
    d.edge('UI', 'GW', label='HTTP loopback (fetch/XHR kèm token)', srcside='bottom', dstside='top', color='#6C8EBF')
    d.edge('splash', 'SHELL', dashed=True,
           srcside='right', dstside='right', color='#999999', waypoints=[(1338, 252), (1338, 114)])
    d.edge('SHELL', 'RT', dashed=True,
           srcside='left', dstside='left', color='#999999', waypoints=[(30, 114), (30, 498)])
    d.edge('GW', 'RT', label='yêu cầu /api… tới backend đã chọn', srcside='bottom', dstside='top', color='#9673A6')
    d.edge('rt1', 'MODELS', srcside='bottom', dstside='top', color='#D6B656')
    d.edge('rt2', 'MODELS', label='LLM qua Model Router', srcside='bottom', dstside='top', color='#D6B656',
           waypoints=[(660, 570)])
    d.edge('rt2', 'db', srcside='bottom', dstside='top', color='#5A5A5A', waypoints=[(960, 570)])
    d.edge('settings', 'keys', label='khóa API (không bao giờ ghi ra file)', dashed=True,
           srcside='bottom', dstside='top', color='#B85450', waypoints=[(805, 300), (1212, 300)])
    return d


# ================================================================ D2
def d2_runtime():
    d = B.Diagram('desktop-runtime-architecture',
                  'D2 · Ba chế độ Backend Runtime của DesktopApp', 1360, 740)
    d.container('TOP', 40, 64, 1280, 96, 'Quản lý chế độ runtime', 'ext')
    d.node('sel', 64, 100, 400, 48,
           'Trình chọn runtime (trang splash đóng gói)\nnguồn DUY NHẤT được phép gọi lệnh Tauri', 'ext', parent='TOP', fontsize=11)
    d.node('json', 494, 100, 380, 48,
           'runtime.json — thư mục cấu hình ứng dụng\n(không chứa bí mật)', 'ext', parent='TOP', fontsize=11.5)
    d.node('cmds', 904, 100, 392, 48,
           'Lệnh Tauri: get_state · pick_folder · validate\n· test_remote · apply · resume', 'ext', parent='TOP', fontsize=11)
    cols = [('A', 40, 'be', '1 · Bundled Core (mặc định)', [
                'Shell chạy sidecar PyInstaller\n(desktop_server.py — Flask không đổi)',
                'UI Gateway chạy như thread trong sidecar',
                'OCR · LLM cục bộ · RAG chạy trên máy người dùng',
                'Dữ liệu: app data dir riêng của DesktopApp']),
            ('C', 480, 'ocr', '2 · WebApp Runtime (external)', [
                'Người dùng chọn thư mục bản WebApp đã cài\n→ shell kiểm tra venv hợp lệ',
                'venv của WebApp chạy desktop-shim/desktop_server.py',
                'MODEL_DIR · GLM dùng từ WebApp —\nDB / uploads VẪN thuộc DesktopApp',
                'GLM MLX helper — chỉ trên macOS Apple Silicon']),
            ('E', 920, 'llm', '3 · Remote Server', [
                'Chỉ UI Gateway chạy cục bộ\n(SMARTDOCS_GATEWAY_ONLY=1)',
                'Không OCR / LLM / DB nào khởi động trên máy',
                'Upstream: server SmartDocs từ xa — HTTPS\n(hoặc HTTP IP LAN riêng + xác nhận)',
                'Server từ xa CHỈ là backend —\nkhông bao giờ là origin của UI'])]
    for cid, x, key, title, rows in cols:
        d.container(cid, x, 186, 400, 380, title, key)
        for i, txt in enumerate(rows):
            d.node('%s%d' % (cid.lower(), i), x + 24, 226 + i * 82, 352, 64, txt, key,
                   parent=cid, fontsize=11)
    d.node('keep', 40, 600, 1280, 56,
           'Giao diện DesktopApp + UI Gateway GIỮ NGUYÊN trong cả 3 chế độ — chuyển chế độ chỉ thay đổi backend đích, không thay đổi UI',
           'fe', bold=True, fontsize=13)
    d.edge('sel', 'json', label='ghi', srcside='right', dstside='left', color='#5B6B7B')
    d.edge('json', 'A', label='mode = bundled', srcside='bottom', dstside='top', color='#3F61A8', waypoints=[(560, 172), (240, 172)])
    d.edge('json', 'C', label='mode = external', srcside='bottom', dstside='top', color='#0E8088')
    d.edge('json', 'E', label='mode = remote', srcside='bottom', dstside='top', color='#D6B656', waypoints=[(810, 172), (1120, 172)])
    return d


# ================================================================ D3
def d3_deployment():
    d = B.Diagram('desktop-deployment',
                  'D3 · Kiến trúc triển khai DesktopApp — mô hình client', 1360, 570)
    d.container('USER', 40, 64, 640, 448, 'Máy người dùng — macOS · Windows · Linux', 'fe')
    d.node('app', 64, 104, 592, 34, 'Ứng dụng SmartDocs Desktop (.app · .exe · AppImage)', 'fe',
           parent='USER', bold=True, fontsize=12.5)
    d.node('shell', 64, 150, 180, 46, 'Tauri Shell (Rust)', 'ext', parent='USER', fontsize=11.5)
    d.node('wv', 256, 150, 190, 46, 'WebView\nGiao diện SmartDocs', 'fe', parent='USER', fontsize=11.5)
    d.node('gw', 458, 150, 198, 46, 'UI Gateway\n127.0.0.1:<cổng> (loopback)', 'agent', parent='USER', fontsize=11)
    d.node('side', 64, 214, 380, 52, 'Sidecar Python (PyInstaller)\nFlask · OCR · RAG · Qwen cục bộ', 'be',
           parent='USER', fontsize=11.5)
    d.node('data', 64, 288, 300, 78, 'Dữ liệu ứng dụng\nSQLite · uploads · artifacts', 'db',
           parent='USER', shape='cyl', fontsize=11)
    d.node('keys', 388, 288, 268, 78, 'Kho khóa HĐH\nKeychain · Credential Manager\n· Secret Service', 'sec',
           parent='USER', fontsize=10.5)
    d.node('rnote', 64, 386, 592, 40,
           'Chế độ Remote Server: sidecar KHÔNG chạy — chỉ còn gateway phục vụ UI', 'note',
           parent='USER', fontsize=11)
    d.container('LAN', 720, 64, 600, 152, 'Máy chủ LLM tự host — LAN / server riêng', 'llm')
    d.node('lansrv', 744, 104, 552, 48, 'Ollama · vLLM · llama.cpp · LM Studio\nAPI OpenAI-compatible (/v1)', 'llm',
           parent='LAN', fontsize=11.5)
    d.node('lannote', 744, 162, 552, 40,
           'Mô hình lớn triển khai TẠI ĐÂY — DesktopApp chỉ là client, không tải trọng số về máy', 'note',
           parent='LAN', fontsize=11)
    d.container('REMOTE', 720, 244, 600, 118, 'Server SmartDocs từ xa (tùy chọn — chế độ Remote)', 'be')
    d.node('rsrv', 744, 286, 552, 54,
           'Flask backend + cơ sở dữ liệu + tài liệu nằm trên server\nkết nối: HTTPS — hoặc HTTP IP LAN riêng + xác nhận rõ ràng', 'be',
           parent='REMOTE', fontsize=11)
    d.container('CLOUD', 720, 392, 600, 118, 'Dịch vụ cloud (tùy chọn)', 'ext')
    d.node('groq', 744, 436, 260, 50, 'Groq API', 'ext', parent='CLOUD')
    d.node('gem', 1036, 436, 260, 50, 'Google Gemini API', 'ext', parent='CLOUD')
    d.edge('wv', 'gw', srcside='right', dstside='left', color='#6C8EBF')
    d.edge('gw', 'side', srcside='bottom', dstside='top', color='#9673A6', waypoints=[(557, 268), (254, 268)])
    d.edge('shell', 'side', label='spawn + token qua stdin', dashed=True, srcside='bottom', dstside='top',
           color='#999999')
    d.edge('side', 'LAN', srcside='right', dstside='left',
           color='#D6B656', waypoints=[(700, 236), (700, 140)])
    d.edge('gw', 'REMOTE', label='chế độ Remote',
           srcside='right', dstside='left', color='#3F61A8', waypoints=[(690, 173), (690, 303)])
    d.edge('side', 'CLOUD', label='HTTPS — BỊ CHẶN khi bật Local-only', dashed=True,
           srcside='left', dstside='left', color='#B85450',
           waypoints=[(30, 240), (30, 545), (690, 545), (690, 451)])
    return d


# ================================================================ D4
def d4_selection_flow():
    d = B.Diagram('desktop-runtime-selection-flow',
                  'D4 · Luồng chọn & khởi động Backend Runtime', 1240, 900)
    X, W = 120, 380
    d.node('s0', X + 60, 70, 260, 44, 'Khởi động DesktopApp', 'fe', shape='ellipse', bold=True)
    d.node('s1', X, 146, W, 52, 'Sinh token khởi chạy (64 hex — OS RNG)\nmở splash đóng gói', 'ext')
    d.node('s2', X, 232, W, 72, 'Ép mở trình chọn runtime?\n(giữ Option/Alt · biến môi trường)', 'sec', shape='diamond', fontsize=11.5)
    d.node('s3', X, 340, W, 44, 'Đọc runtime.json → chế độ đã lưu', 'ext')
    d.node('s4', X, 416, W, 60, 'Kiểm tra & lập kế hoạch khởi chạy (StartPlan)\nbundled · external (validate venv) · remote (chính sách URL)', 'be', fontsize=11)
    d.node('s5', X, 508, W, 44, 'Chạy sidecar / gateway — token qua stdin', 'be')
    d.node('s6', X, 584, W, 44, 'Handshake stdout ≤ 90 giây → cổng gateway', 'be')
    d.node('s7', X, 660, W, 44, 'Thăm dò /api/desktop/health ≤ 30 giây (kèm token)', 'be')
    d.node('s8', X, 736, W, 56, 'WebView → /desktop/boot → cookie phiên\n→ giao diện SmartDocs (cùng origin)', 'fe')
    d.node('s9', X + 100, 824, 180, 40, 'Sẵn sàng', 'rag', shape='ellipse', bold=True)
    for a, b in [('s0', 's1'), ('s1', 's2'), ('s3', 's4'), ('s4', 's5'), ('s5', 's6'),
                 ('s6', 's7'), ('s7', 's8'), ('s8', 's9')]:
        d.edge(a, b, srcside='bottom', dstside='top')
    d.edge('s2', 's3', label='không', srcside='bottom', dstside='top')
    d.table('entry', 640, 146, 540, 'Các lối vào Trình chọn Runtime (không phụ thuộc backend)', [
        ('Menu gốc: Backend Runtime…  (Cmd/Ctrl + ,)', ''),
        ('Nút “Đổi backend…” trên màn hình lỗi (splash · trang 502 của gateway)', ''),
        ('Giữ Option/Alt trong lúc khởi động', ''),
        ('Biến môi trường SMARTDOCS_FORCE_RUNTIME_SELECTOR=1', ''),
    ], 'ext', rowh=24)
    d.node('selector', 640, 416, 540, 60,
           'Trình chọn Runtime (trang splash)\nruntime_validate · runtime_test_remote · runtime_apply · runtime_resume',
           'llm', fontsize=11.5)
    d.node('fail', 640, 560, 540, 56,
           'Khởi chạy LỖI → mở trình chọn kèm thông báo lỗi\nruntime.json được GIỮ NGUYÊN để người dùng sửa', 'sec', fontsize=11.5)
    d.edge('s2', 'selector', label='có', srcside='right', dstside='left', color='#B85450',
           waypoints=[(560, 268), (560, 446)])
    d.edge('entry', 'selector', srcside='bottom', dstside='top', color='#5B6B7B')
    d.edge('s5', 'fail', label='lỗi', dashed=True, srcside='right', dstside='left', color='#B85450',
           waypoints=[(580, 530), (580, 588)])
    d.edge('s6', 'fail', dashed=True, srcside='right', dstside='left', color='#B85450',
           waypoints=[(580, 606), (580, 588)])
    d.edge('s7', 'fail', dashed=True, srcside='right', dstside='left', color='#B85450',
           waypoints=[(580, 682), (580, 588)])
    d.edge('fail', 'selector', srcside='top', dstside='bottom', color='#B85450')
    d.edge('selector', 's4', label='áp dụng & tiếp tục', srcside='left', dstside='right', color='#82B366')
    return d


# ================================================================ D5
def d5_gateway_flow():
    d = B.Diagram('desktop-gateway-flow',
                  'D5 · UI Gateway — luồng xử lý yêu cầu (mọi chế độ runtime)', 1360, 680)
    d.node('wv', 50, 120, 240, 56, 'WebView\nGiao diện DesktopApp', 'fe', bold=True)
    d.node('host', 340, 108, 230, 80, 'Host là 127.0.0.1 /\nlocalhost / ::1 ?', 'sec', shape='diamond', fontsize=11.5)
    d.node('deny', 350, 236, 210, 40, 'Từ chối — chống DNS-rebinding', 'sec', fontsize=11)
    routes = [('c1', 'GET / · /agent · /static/*', 't1', 'Asset giao diện DesktopApp\n(cục bộ — trong MỌI chế độ)', 'fe'),
              ('c2', '/api/desktop/health · /api/desktop/shutdown', 't2', 'Trả lời ngay tại gateway\n(shutdown yêu cầu token)', 'agent'),
              ('c3', '/api/* · /login · /logout · /admin(/…)', 't3', 'Proxy tới backend upstream', 'be'),
              ('c4', 'Đường dẫn khác', 't4', '404 — không phục vụ', 'ext')]
    for i, (cid, clab, tid, tlab, tkey) in enumerate(routes):
        y = 96 + i * 72
        d.node(cid, 630, y, 340, 52, clab, 'agent', fontsize=11.5)
        d.node(tid, 1020, y, 300, 52, tlab, tkey, fontsize=11.5)
        d.edge(cid, tid, srcside='right', dstside='left')
        d.edge('host', cid, srcside='right', dstside='left', color='#82B366',
               label=('hợp lệ' if i == 0 else ''))
    d.edge('wv', 'host', srcside='right', dstside='left')
    d.edge('host', 'deny', label='sai Host', srcside='bottom', dstside='top', color='#B85450')
    d.table('bhv', 50, 400, 640, 'Hành vi proxy (giống nhau ở mọi chế độ)', [
        ('Stream 2 chiều không đệm — upload · download · SSE', ''),
        ('Không follow redirect — Location cùng origin được viết lại về origin gateway', ''),
        ('Set-Cookie: bỏ Domain/Secure → phiên bám vào origin cục bộ', ''),
        ('Chế độ Remote: gỡ header X-SmartDocs-Token — token không bao giờ rời máy', ''),
        ('Kết nối LAN không an toàn → hiển thị chip cảnh báo cố định trên UI', ''),
    ], 'note', rowh=24)
    d.node('up1', 1020, 420, 300, 56, 'Bundled / WebApp Runtime:\nFlask trong tiến trình sidecar', 'be', fontsize=11.5)
    d.node('up2', 1020, 500, 300, 56, 'Remote: server SmartDocs từ xa\n(trang được gate đăng nhập qua /api/auth/me)', 'llm', fontsize=11)
    d.edge('t3', 'up1', srcside='bottom', dstside='top', color='#3F61A8')
    d.edge('t3', 'up2', srcside='bottom', dstside='top', color='#D6B656', waypoints=[(1350, 336), (1350, 528)])
    return d


# ================================================================ D6 (shared shape with WebApp)
def build_model_routing(name, title, note_consumers):
    d = B.Diagram(name, title, 1360, 700)
    d.container('SET', 40, 64, 620, 180, 'Cài đặt → AI models', 'fe')
    d.node('cfg1', 64, 104, 572, 48,
           'Định tuyến theo tác vụ (task_models):\nChat / Hỏi đáp tài liệu · Tóm tắt · Viết lại AI · Agent', 'fe',
           parent='SET', fontsize=11.5)
    d.node('cfg2', 64, 160, 572, 36, 'Model dự phòng (fallback_model) — tùy chọn, chính sách tường minh', 'fe',
           parent='SET', fontsize=11.5)
    d.node('cfg3', 64, 202, 572, 36, 'Mặc định: Automatic (auto) = giữ nguyên hành vi trước đây', 'fe',
           parent='SET', fontsize=11.5)
    d.container('CONS', 700, 64, 620, 180, note_consumers, 'rag')
    d.node('u1', 724, 104, 286, 48, 'Chat / Hỏi đáp tài liệu', 'rag', parent='CONS', fontsize=12)
    d.node('u2', 1030, 104, 266, 48, 'Tóm tắt · Viết lại AI', 'rag', parent='CONS', fontsize=12)
    d.node('u3', 724, 168, 572, 48, 'Agent — lập kế hoạch & tổng hợp (tác vụ “agent”)', 'rag',
           parent='CONS', fontsize=12)
    d.container('ROUTE', 40, 270, 1280, 226, 'Model Router — llm_gateway.resolve(task)', 'agent')
    d.node('auto', 64, 310, 390, 76,
           'auto → chuỗi legacy (offline-first):\nGroq → Gemini → self-hosted → Qwen cục bộ\n(cloud chỉ khi CÓ khóa và ĐƯỢC phép)', 'agent',
           parent='ROUTE', fontsize=11)
    d.node('expl', 478, 310, 390, 76,
           'Model chỉ định → kiểm tra:\ncòn tồn tại · hỗ trợ tác vụ · đã cấu hình\nLocal-only ⇒ chặn model cloud', 'agent',
           parent='ROUTE', fontsize=11)
    d.node('err', 892, 310, 404, 76,
           'Không đạt ⇒ RouteError (thông báo rõ, xử lý được)\nKHÔNG âm thầm đổi model\nKHÔNG fallback ngầm sang cloud', 'sec',
           parent='ROUTE', fontsize=11)
    d.node('fit', 64, 406, 520, 56,
           'Vừa khít ngữ cảnh: cắt prompt theo context_limit\ncủa model (ưu tiên nội dung mới nhất)', 'agent',
           parent='ROUTE', fontsize=11)
    d.node('fb', 608, 406, 688, 56,
           'fallback_model (nếu đặt) chỉ được dùng khi vượt qua CÙNG các kiểm tra —\nfallback bị chặn không bao giờ được thay thế vào', 'agent',
           parent='ROUTE', fontsize=11)
    d.container('REG', 40, 522, 1280, 142, 'Model Registry — danh mục model (không bao giờ giữ khóa API)', 'llm')
    rx = B.row_x(64, 1296, 5, 236)
    regs = ['Bundled local\nQwen cục bộ (CPU)\nctx ~4096',
            'Managed local\nsnapshot HF (tùy chọn)',
            'Self-hosted (OpenAI-compatible)\nOllama · vLLM · llama.cpp\n· LM Studio',
            'Groq (cloud)\ncần khóa API · ctx 32k',
            'Gemini (cloud)\ncần khóa API · ctx 131k']
    for i, lab in enumerate(regs):
        d.node('r%d' % i, int(rx[i]), 562, 236, 76, lab, 'llm', parent='REG', fontsize=10.5)
    d.edge('SET', 'ROUTE', label='cấu hình', dashed=True, srcside='bottom', dstside='top', color='#6C8EBF')
    d.edge('CONS', 'ROUTE', label='resolve(task)', srcside='bottom', dstside='top', color='#82B366')
    d.edge('ROUTE', 'REG', label='tra cứu model → build provider (+ fit ngữ cảnh)', srcside='bottom', dstside='top', color='#D6B656')
    return d


def d6_model_routing():
    return build_model_routing(
        'desktop-model-routing',
        'D6 · Định tuyến mô hình AI theo tác vụ — Model Registry & Router',
        'Các consumer LLM (mọi lời gọi đều hỏi Router)')


# ================================================================ D7 (shared shape with WebApp)
def build_privacy(name, title, url_scope):
    d = B.Diagram(name, title, 1360, 650)
    d.container('LO', 40, 64, 620, 196, 'Local-only (Cài đặt → Quyền riêng tư)', 'sec')
    d.node('lo1', 64, 104, 572, 42, 'CHẶN Groq · Gemini — không dữ liệu nào được gửi lên cloud', 'sec',
           parent='LO', fontsize=11.5)
    d.node('lo2', 64, 154, 572, 42, 'CHO PHÉP model cục bộ và server tự host (mạng của bạn)', 'rag',
           parent='LO', fontsize=11.5)
    d.node('lo3', 64, 204, 572, 42, 'Không fallback ngầm sang cloud — báo lỗi rõ ràng, có hướng xử lý', 'sec',
           parent='LO', fontsize=11.5)
    d.container('KEY', 700, 64, 620, 196, 'Khóa API — CHỈ nằm trong kho khóa hệ điều hành', 'be')
    d.node('k1', 724, 104, 572, 42, 'Keychain (macOS) · Credential Manager (Windows) · Secret Service (Linux)', 'be',
           parent='KEY', fontsize=11.5)
    d.node('k2', 724, 154, 572, 42, 'Không bao giờ ghi khóa thô vào file cài đặt — UI chỉ hiển thị dạng che', 'be',
           parent='KEY', fontsize=11.5)
    d.node('k3', 724, 204, 572, 42, 'Kho khóa không khả dụng → cảnh báo rõ + TỪ CHỐI lưu (không âm thầm)', 'be',
           parent='KEY', fontsize=11.5)
    d.table('url', 40, 296, 620, url_scope, [
        ('HTTPS', 'luôn cho phép'),
        ('HTTP → localhost / 127.0.0.1 / ::1', 'cho phép'),
        ('HTTP → IP LAN riêng (10/8 · 172.16/12 · 192.168/16 · fc00::/7)', 'bật tùy chọn + xác nhận'),
        ('HTTP → địa chỉ công cộng hoặc hostname', 'từ chối'),
        ('URL chứa thông tin đăng nhập (user:pass@)', 'từ chối'),
        ('Hạ cấp HTTPS xuống HTTP', 'không bao giờ'),
    ], 'llm', rowh=24)
    d.table('probe', 700, 296, 620, 'Kiểm tra kết nối self-hosted — các trạng thái hiển thị', [
        ('Đã kết nối (connected) — server & model sẵn sàng', ''),
        ('Không truy cập được (unavailable)', ''),
        ('Xác thực thất bại (auth_failed — 401 · 403)', ''),
        ('Không tìm thấy model (model_not_found)', ''),
        ('Phản hồi không tương thích (incompatible)', ''),
        ('Hết thời gian chờ (timeout)', ''),
        ('Bị chính sách URL chặn (policy_blocked)', ''),
        ('Giới hạn ngữ cảnh quá nhỏ (context_insufficient)', ''),
    ], 'rag', rowh=24)
    d.node('note', 40, 546, 1280, 56,
           'Kiểm tra kết nối: GET /v1/models (kèm Bearer nếu có khóa) → nếu server không hỗ trợ, thử chat completion tối thiểu (max_tokens = 1).\nKHÔNG bao giờ gửi nội dung tài liệu ra ngoài khi kiểm tra.',
           'note', fontsize=11.5)
    return d


def d7_privacy():
    return build_privacy(
        'desktop-privacy-local-only',
        'D7 · Quyền riêng tư — Local-only · khóa API · chính sách URL',
        'Chính sách URL — server tự host & Remote Server')


# ================================================================ D8
def d8_document_flow():
    d = B.Diagram('desktop-document-flow',
                  'D8 · Vòng đời tài liệu — OCR · xử lý · chat kèm trích dẫn', 1360, 540)
    d.node('where', 40, 64, 1280, 44,
           'Toàn bộ luồng chạy trong backend đã chọn — Bundled / WebApp Runtime: ngay trên máy người dùng · Remote Server: trên server (máy này chỉ hiển thị UI)',
           'note', fontsize=11.5)
    xs = B.row_x(40, 1320, 4, 290)
    r1 = [('up', 'Tải tài liệu lên\nPOST /api/upload (PDF · ảnh · DOCX…)', 'fe'),
          ('ocr', 'OCR engine\nPaddleOCR (legacy · modern)\nVietOCR · GLM-OCR', 'ocr'),
          ('ext', 'Trích xuất cấu trúc\nmarkdown · bảng · bố cục', 'ocr'),
          ('art', 'Artifacts\nmarkdown · JSON · ảnh trích xuất', 'db')]
    for i, (nid, lab, key) in enumerate(r1):
        d.node(nid, int(xs[i]), 140, 290, 64, lab, key, fontsize=11)
    r2 = [('corr', 'Sửa lỗi (correction)', 'ai'),
          ('tran', 'Dịch thuật (Google / Argos)', 'ai'),
          ('summ', 'Tóm tắt · Viết lại AI', 'ai'),
          ('rag', 'RAG index\nSBERT / hashing + FAISS', 'rag')]
    for i, (nid, lab, key) in enumerate(r2):
        d.node(nid, int(xs[i]), 268, 290, 64, lab, key, fontsize=11.5)
    d.node('chat', 700, 396, 620, 64, 'Chat / Hỏi đáp tài liệu — trả lời kèm TRÍCH DẪN từ tài liệu', 'rag',
           bold=True, fontsize=12.5)
    d.node('llm', 40, 396, 560, 64, 'LLM qua Model Router\n(Chat/QA · Tóm tắt · Viết lại — theo Cài đặt AI models)', 'agent',
           fontsize=11.5)
    d.edge('up', 'ocr', srcside='right', dstside='left')
    d.edge('ocr', 'ext', srcside='right', dstside='left')
    d.edge('ext', 'art', srcside='right', dstside='left')
    for t in ('corr', 'tran', 'summ', 'rag'):
        d.edge('art', t, srcside='bottom', dstside='top', color='#5A5A5A')
    d.edge('rag', 'chat', srcside='bottom', dstside='top', color='#82B366')
    d.edge('chat', 'llm', label='resolve(task)', dashed=True, srcside='left', dstside='right', color='#9673A6')
    d.edge('summ', 'llm', dashed=True, srcside='bottom', dstside='top', color='#9673A6',
           waypoints=[(845, 372), (320, 372)])
    return d


# ================================================================ D9
def d9_agent_flow():
    d = B.Diagram('desktop-agent-flow',
                  'D9 · Luồng thực thi Agent — vòng lặp tool có giới hạn', 1360, 700)
    d.node('ui', 40, 80, 260, 56, 'Trang Agent\n(giao diện riêng /agent)', 'fe', bold=True)
    d.node('bp', 340, 80, 340, 56, 'agent_bp — POST /api/agent/run\nphạm vi: CHỈ các tài liệu được phép (tenancy)', 'be',
           fontsize=11.5)
    d.container('CORE', 40, 176, 900, 300,
                'AgentCore — vòng lặp suy luận (giới hạn bước + ngân sách thời gian)', 'agent')
    d.node('think', 64, 226, 260, 64, '1 · Suy nghĩ\nLLM chọn hành động kế tiếp', 'agent', parent='CORE', fontsize=11.5)
    d.node('act', 354, 226, 260, 64, '2 · Hành động\ngọi tool qua ToolRegistry', 'agent', parent='CORE', fontsize=11.5)
    d.node('obs', 644, 226, 272, 64, '3 · Quan sát\nkết quả có cấu trúc của tool', 'agent', parent='CORE', fontsize=11.5)
    d.node('synth', 64, 330, 852, 52,
           'Hết bước / hết giờ → MỘT lượt tổng hợp cuối (không gọi thêm tool) — kết quả đánh dấu completed / timed_out',
           'llm', parent='CORE', fontsize=11.5)
    d.node('prog', 64, 402, 852, 48,
           'Phát tiến trình run theo thời gian thực lên UI: thinking → acting → observation', 'agent',
           parent='CORE', fontsize=11.5)
    d.container('TOOLS', 40, 508, 900, 134, 'Bộ tool an toàn cho Agent (HTTP-safe set)', 'ai')
    tx = B.row_x(64, 916, 5, 160)
    tools = ['chat\nHỏi đáp tài liệu', 'knowledge_search\ntìm kiếm tri thức', 'summarize\ntóm tắt',
             'translate\ndịch thuật', 'correct\nsửa lỗi']
    for i, lab in enumerate(tools):
        d.node('t%d' % i, int(tx[i]), 556, 160, 60, lab, 'ai', parent='TOOLS', fontsize=11)
    d.node('llm', 980, 226, 340, 64, 'LLM qua Model Router\ntác vụ “agent” (auto → chuỗi legacy)', 'llm', fontsize=11.5)
    d.node('guard', 980, 330, 340, 64, 'Giới hạn an toàn: ngữ cảnh bị chặn trên;\nOcrTool KHÔNG lộ ra bề mặt agent', 'sec',
           fontsize=11.5)
    d.node('result', 980, 508, 340, 72, 'Kết quả + artifacts của run\n(không ghi đè artifact hiện có)', 'db',
           fontsize=11.5)
    d.edge('ui', 'bp', srcside='right', dstside='left')
    d.edge('bp', 'CORE', srcside='bottom', dstside='top', color='#9673A6')
    d.edge('think', 'act', srcside='right', dstside='left')
    d.edge('act', 'obs', srcside='right', dstside='left')
    d.edge('obs', 'think', label='lặp (≤ max_steps · còn thời gian)', srcside='bottom', dstside='bottom',
           color='#9673A6', waypoints=[(780, 308), (194, 308)])
    d.edge('CORE', 'TOOLS', label='gọi tool', srcside='bottom', dstside='top', color='#D79B00')
    d.edge('think', 'llm', srcside='right', dstside='left', color='#D6B656', waypoints=[(960, 210)])
    d.edge('synth', 'result', srcside='right', dstside='top', color='#5A5A5A',
           waypoints=[(960, 356), (960, 470), (1150, 470)])
    return d


DIAGRAMS = [d1_overall, d2_runtime, d3_deployment, d4_selection_flow, d5_gateway_flow,
            d6_model_routing, d7_privacy, d8_document_flow, d9_agent_flow]

if __name__ == '__main__':
    for fn in DIAGRAMS:
        write(fn())
