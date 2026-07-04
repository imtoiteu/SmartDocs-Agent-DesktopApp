/* ═══════════════════════════════════════════════════════════
   SmartDocs Platform — i18n.js
   Internationalization module: Vietnamese (default) + English
   Add more languages by extending the TRANSLATIONS object.
   ═══════════════════════════════════════════════════════════ */

const TRANSLATIONS = {

  // ── Vietnamese (default) ───────────────────────────────
  vi: {
    // App branding
    app_name:          'SmartDocs Platform',
    app_tagline:       'Nền tảng tài liệu AI',

    // Navigation
    nav_home:          '🏠 Trang chủ',
    nav_ocr:           '🔍 OCR',
    nav_correct:       '✏️ Sửa lỗi',
    nav_translate:     '🌐 Dịch thuật',
    nav_summarize:     '📝 Tóm tắt',
    nav_documents:     '📁 Tài liệu',
    nav_admin:         '⚙️ Quản trị',
    nav_settings:      '⚙ Cài đặt',
    nav_sign_out:      '⏏ Đăng xuất',

    // Settings (cloud keys + privacy)
    settings_privacy_title: '🔒 Quyền riêng tư — nơi xử lý AI',
    settings_privacy_desc:  '“Cho phép xử lý đám mây” nghĩa là văn bản tài liệu, trích đoạn và câu lệnh có thể được gửi đến nhà cung cấp đám mây đã cấu hình. “Chỉ cục bộ” giữ mọi thứ trên máy này (dịch ngoại tuyến, mô hình cục bộ).',
    settings_keys_title:    '🔑 Khóa API nhà cung cấp đám mây',
    settings_keys_desc:     'Khóa được lưu trong kho thông tin xác thực của hệ điều hành (macOS Keychain / Windows Credential Manager / Linux Secret Service) — không bao giờ lưu vào tệp hay cơ sở dữ liệu. Chỉ 4 ký tự cuối được hiển thị.',
    settings_loading:       'Đang tải…',
    settings_mode_local:    '🔒 Chỉ cục bộ — không gửi gì lên đám mây',
    settings_mode_cloud:    '☁ Đã cho phép xử lý đám mây',
    settings_enable_cloud:  'Cho phép xử lý đám mây…',
    settings_disable_cloud: 'Chuyển sang Chỉ cục bộ',
    settings_env_locked:    'Được đặt bởi ALLOW_CLOUD trong .env — xóa ở đó để điều khiển tại đây.',
    settings_cloud_on:      'Đã cho phép xử lý đám mây.',
    settings_cloud_off:     'Đã bật Chỉ cục bộ — không gì rời khỏi máy này.',
    settings_state_none:        'Chưa cấu hình',
    settings_state_configured:  'Đã cấu hình',
    settings_state_testing:     'Đang kiểm tra…',
    settings_state_connected:   'Đã kết nối',
    settings_state_invalid:     'Khóa không hợp lệ',
    settings_state_error:       'Không thể kết nối',
    settings_state_unavailable: 'Kho thông tin xác thực không khả dụng',
    settings_state_blocked:     'Chỉ cục bộ',
    settings_keyring_unavailable: 'Kho thông tin xác thực của hệ điều hành không khả dụng — không thể lưu khóa tại đây. ',
    settings_local_only_keys: 'Chế độ Chỉ cục bộ đang bật — khóa đám mây không được dùng hay kiểm tra.',
    settings_from_env:      'từ .env',
    settings_env_key:       'Khóa này đến từ .env và được ưu tiên hơn khóa đã lưu.',
    settings_btn_save:      'Lưu',
    settings_btn_test:      'Kiểm tra',
    settings_btn_remove:    'Xóa',
    settings_key_enter:     'Dán khóa API…',
    settings_key_replace:   'Nhập khóa mới để thay thế…',
    settings_key_required:  'Hãy nhập khóa API trước.',
    settings_key_saved:     'Đã lưu khóa vào kho thông tin xác thực của hệ điều hành.',
    settings_key_removed:   'Đã xóa khóa.',
    settings_key_remove_confirm: 'Xóa khóa API đã lưu của nhà cung cấp này?',
    settings_save_failed:   'Không thể lưu.',
    settings_load_failed:   'Không thể tải cài đặt.',
    engine_local_only:      '🔒 Chỉ cục bộ — dịch ngoại tuyến (xem Cài đặt)',

    // Home page
    home_hero_title:   'Nền tảng tài liệu AI',
    home_hero_sub:     'Trích xuất, sửa lỗi, dịch thuật và tóm tắt văn bản từ hình ảnh, PDF và tài liệu.',

    // Tool cards
    tc_ocr_title:      'Trích xuất OCR',
    tc_ocr_desc:       'Trích xuất văn bản từ hình ảnh và PDF với trực quan hóa vùng nhận dạng.',
    tc_correct_title:  'Sửa lỗi văn bản',
    tc_correct_desc:   'Tự động sửa lỗi OCR, lỗi chính tả, ngữ pháp và định dạng văn bản.',
    tc_translate_title:'Dịch thuật',
    tc_translate_desc: 'Dịch văn bản giữa các ngôn ngữ với tính năng tự động nhận diện ngôn ngữ.',
    tc_summarize_title:'Tóm tắt',
    tc_summarize_desc: 'Tạo tóm tắt ngắn, gạch đầu dòng hoặc tóm tắt điều hành từ bất kỳ văn bản nào.',
    tc_documents_title:'Tài liệu',
    tc_documents_desc: 'Quản lý, mở lại và tải xuống các tài liệu cùng kết quả OCR đã lưu.',
    tc_chat_title:     'SmartDocs AI',
    tc_chat_desc:      'Trò chuyện với AI: hỏi đáp tổng quát hoặc hỏi trực tiếp trên một tài liệu.',
    tc_agent_title:    'Agent',
    tc_agent_desc:     'Trợ lý tự động điều phối nhiều công cụ để hoàn thành tác vụ phức tạp.',
    tc_admin_title:    'Quản trị',
    tc_admin_desc:     'Quản lý người dùng, theo dõi hoạt động và cấu hình hệ thống.',
    get_started:       'Bắt đầu →',

    // OCR panel
    ocr_extract:       'Trích xuất OCR',
    ocr_upload_hint:   'Tải lên hình ảnh hoặc PDF để trích xuất văn bản',
    ocr_drop_hint:     'Kéo thả file vào đây hoặc',
    ocr_drop_full:     'Kéo thả tệp vào đây hoặc <span style="color:var(--accent2)">nhấp để duyệt</span>',
    ocr_click_browse:  'nhấp để duyệt',
    ocr_file_formats:  'JPG · PNG · WEBP · PDF (nhiều trang)',
    run_ocr:           '▶ Chạy OCR',
    ocr_all:           '⚡ Tất cả trang',
    ocr_reset:         '↩ Đặt lại',
    ocr_file_label:    'Tệp',
    ocr_summary:       'Tổng quan',
    ocr_regions:       'Vùng',
    ocr_avg_conf:      'Độ tin cậy',
    ocr_time:          'Thời gian',
    ocr_pages:         'Trang',
    ocr_extracted_text:'Văn bản đã trích xuất',
    ocr_detections:    'Kết quả phát hiện',
    ocr_copy:          '📋 Sao chép',
    ocr_dl_txt:        '⬇ TXT',
    ocr_dl_md:         '⬇ MD',
    ocr_dl_json:       '⬇ JSON',
    ocr_tab_md:        '📝 Markdown',
    ocr_tab_raw:       '⟨⟩ Nguồn',
    ocr_tab_images:    '🖼 Hình ảnh',
    ocr_tab_json:      '{ } JSON',
    ocr_select_region: '🔳 Chọn vùng',
    ocr_send_to:       'Gửi đến',
    send_correct:      '→ Sửa lỗi',
    send_translate:    '→ Dịch thuật',
    send_summarize:    '→ Tóm tắt',
    run_ocr_running:   'Đang chạy…',
    ocr_all_running:   'Đang xử lý…',
    ocr_empty:         'Chạy OCR để xem kết quả',
    ocr_layout_label:  'Bố cục:',
    ocr_layout_original: 'Gốc',
    ocr_layout_enhanced: '✨ Nâng cao',
    ocr_engine_label:  'Công cụ:',
    ocr_engine_recommended: '⭐ Khuyên dùng',
    ocr_engine_vietnamese:  '🇻🇳 Tiếng Việt',
    ocr_engine_standard:    '📄 Tiêu chuẩn',
    ocr_ai_label:      'Dọn dẹp AI:',
    ocr_ai_off:        'Tắt',
    ocr_ai_on:         '🧠 Bật',
    ocr_mode_standard: '📄 Standard',
    ocr_mode_smart:    '🧠 Smart OCR',
    ocr_mode_tooltip:  'Standard: OCR chuẩn. Smart: OCR + AI nâng cao (sắp ra mắt)',

    // Correct panel
    correct_title:     'Sửa lỗi văn bản',
    correct_result:    'Kết quả',
    correct_paste:     'Dán văn bản',
    correct_upload:    'Tải lên',
    correct_placeholder:'Dán văn bản cần sửa lỗi…',
    correct_run:       '✨ Sửa lỗi',
    correct_running:   'Đang sửa…',
    correct_empty:     'Văn bản đã sửa sẽ hiển thị ở đây',
    correct_import:    '📥 Nhập từ OCR',
    send_to:           'Gửi đến',

    // Translate panel
    translate_title:   'Dịch thuật',
    translate_result:  'Kết quả dịch',
    translate_input_label: 'Văn bản đầu vào',
    translate_placeholder: 'Nhập văn bản cần dịch…',
    translate_run:     '🌐 Dịch',
    translate_running: 'Đang dịch…',
    translate_empty:   'Bản dịch sẽ hiển thị ở đây',
    translate_import:  '📥 Nhập từ OCR',
    translate_engine:  'Công cụ dịch',
    engine_auto:       '⚡ Tự động',
    engine_recommended:'Khuyên dùng',
    engine_online:     '🌐 Trực tuyến',
    engine_offline:    '📴 Ngoại tuyến',
    engine_checking:   'Đang kiểm tra…',
    auto_detect:       'Tự động nhận diện',
    engine_no_internet:      'Không có kết nối Internet',
    engine_warn_online_no_net: 'Chế độ Trực tuyến yêu cầu kết nối Internet.',
    engine_warn_offline_missing: 'Bộ dịch Ngoại tuyến chưa được cài đặt.',
    engine_online_required:  'Chế độ Trực tuyến yêu cầu Internet.',
    engine_used_online:  'Google Translate',
    engine_used_offline: 'Dịch ngoại tuyến',
    engine_used_auto:    'Tự động',
    engine_fallback:     'Dự phòng',
    engine_rechecking:       'Đang kiểm tra lại kết nối…',
    engine_internet_restored: 'Đã phát hiện kết nối mạng. Đang kiểm tra…',
    engine_internet_back:    'Kết nối Internet đã khôi phục. Chế độ Trực tuyến sẵn sàng!',
    engine_disabled_click:   'Nhấp để kiểm tra lại kết nối',
    lang_vi:           'Tiếng Việt',
    lang_en:           'Tiếng Anh',
    lang_zh:           'Tiếng Trung',
    lang_ja:           'Tiếng Nhật',
    lang_ko:           'Tiếng Hàn',
    lang_fr:           'Tiếng Pháp',
    lang_de:           'Tiếng Đức',
    lang_es:           'Tiếng Tây Ban Nha',

    // Chat history panel (persistence)
    'chat.history':       'Lịch sử trò chuyện',
    'chat.new':           'Cuộc trò chuyện mới',
    'chat.history_empty': 'Chưa có cuộc trò chuyện nào.',
    'chat.general_group': 'Trợ lý chung',
    'chat.rename':        'Đổi tên',
    'chat.delete':        'Xóa',
    'chat.need_doc':      'Hãy mở một cuộc trò chuyện tài liệu hoặc chuyển sang Trợ lý chung.',
    'chat.view_doc':      'Xem tài liệu',
    doc_not_found:        'Không tìm thấy tài liệu',
    'nav.back':           'Quay lại',

    // Summarize panel
    summarize_title:   'Tóm tắt',
    summarize_result:  'Bản tóm tắt',
    summarize_placeholder:'Dán văn bản cần tóm tắt…',
    summarize_mode:    'Chế độ tóm tắt',
    mode_short:        '📄 Ngắn gọn',
    mode_bullets:      '• Gạch đầu dòng',
    mode_executive:    '📊 Điều hành',
    summarize_run:     '📝 Tóm tắt',
    summarize_running: 'Đang tóm tắt…',
    summarize_empty:   'Bản tóm tắt sẽ hiển thị ở đây',
    summarize_import:  '📥 Nhập từ OCR',
    // Engine selector (Fast mode)
    sum_engine_label:  'Bộ máy tóm tắt',
    sum_engine_auto:   '⚡ Tự động',
    sum_engine_fast:   'Nhanh',
    sum_engine_smart:  'Thông minh (VI)',
    sum_engine_rec:    'Khuyên dùng',
    engine_recommended:'Khuyên dùng',
    // Dual-mode selector
    sum_mode_label:    'Chế độ tóm tắt',
    sum_mode_fast:     'Tóm tắt nhanh',
    sum_mode_fast_rec: 'Khuyên dùng',
    sum_mode_ai:       'AI Viết lại',
    // AI status
    sum_ai_checking:   'Đang kiểm tra…',
    sum_ai_loading:    'Đang tải mô hình AI…',
    sum_ai_ready:      '🧠 AI · Sẵn sàng',
    sum_ai_ready_word: 'Sẵn sàng',
    sum_ai_api:        '🌐 API · Sẵn sàng',
    sum_ai_unavailable:'AI không khả dụng — sẽ dùng Fast',
    // Output style pill labels
    mode_short_lbl:    'Ngắn gọn',
    mode_bullets_lbl:  'Gạch đầu dòng',
    mode_exec_lbl:     'Điều hành',

    // Documents panel
    docs_title:        '📁 Tài liệu',
    docs_sub:          'Quản lý các tệp đã tải lên',
    docs_refresh:      '↻ Làm mới',
    docs_all:          'Tất cả',
    docs_images:       '🖼 Hình ảnh',
    docs_pdfs:         '📜 PDF',
    docs_text:         '📄 Văn bản',
    docs_search:       'Tìm kiếm tệp…',
    docs_col_file:     'Tệp',
    docs_col_type:     'Loại',
    docs_col_size:     'Kích thước',
    docs_col_owner:    'Chủ sở hữu',
    docs_col_uploaded: 'Ngày tải lên',
    docs_col_status:   'Trạng thái',
    docs_col_actions:  'Thao tác',
    docs_empty:        'Chưa có tài liệu nào. Tải lên tệp để bắt đầu.',
    docs_loading:      'Đang tải…',
    pagination_showing: 'Hiển thị',
    pagination_of:      'trong số',
    pagination_items:   'tài liệu',
    docs_loading:      'Đang tải…',
    docs_delete_confirm: 'Xóa tài liệu này? Không thể hoàn tác.',
    docs_deleted:      'Đã xóa',
    // Docs stats chips
    docs_stat_total:   'Tổng cộng',
    docs_stat_images:  'Hình ảnh',
    docs_stat_pdfs:    'PDF',
    docs_stat_texts:   'Tệp văn bản',
    // Docs action tooltips
    docs_tip_ocr:      'Chạy OCR',
    docs_tip_correct:  'Sửa lỗi văn bản',
    docs_tip_translate:'Dịch thuật',
    docs_tip_summarize:'Tóm tắt',
    docs_tip_download: 'Tải xuống',
    docs_tip_delete:   'Xóa',
    // Translate engine status
    engine_status_all:    '🟢 Trực tuyến + Ngoại tuyến sẵn sàng',
    engine_status_online: '🌐 Trực tuyến sẵn sàng',
    engine_status_offline:'📴 Chỉ ngoại tuyến',
    engine_status_none:   '⚠️ Không có công cụ nào',
    engine_status_error:  '⚠️ Không thể kiểm tra trạng thái',
    engine_offline_tip:   'Dịch ngoại tuyến chưa khả dụng',
    engine_online_tip:    'Không có kết nối internet',
    // File loaded
    toast_file_loaded: 'Đã tải',

    // Upload zone
    upload_txt_docx_pdf: 'Tải lên TXT / DOCX / PDF',

    // Common
    copy:              '📋 Sao chép',
    download_txt:      '⬇ TXT',
    copied:            'Đã sao chép!',
    copy_failed:       'Sao chép thất bại',
    copy_nothing:      'Không có nội dung để sao chép',
    loading:           'Đang tải…',
    cancel:            'Hủy',
    paste_tab:         'Dán văn bản',
    upload_tab:        'Tải lên',

    // Toast messages
    toast_text_copied: 'Đã sao chép văn bản!',
    toast_region_copied: 'Đã sao chép văn bản trong vùng chọn!',
    toast_unsupported: 'Loại tệp không được hỗ trợ',
    toast_no_text:     'Vui lòng nhập hoặc nhập văn bản trước.',
    toast_no_ocr:      'Chưa có kết quả OCR. Hãy chạy OCR trước.',
    toast_ocr_imported:'Đã nhập văn bản OCR!',
    toast_no_output:   'Không có đầu ra để gửi',
    toast_correct_done:'Văn bản đã được sửa lỗi!',
    toast_translate_done:'Dịch thuật hoàn tất!',
    toast_summarize_done:'Tóm tắt đã sẵn sàng!',
    toast_load_fail:   'Không thể tải tài liệu',
    toast_read_fail:   'Không thể đọc tệp: ',
    toast_imported:    'Đã nhập văn bản!',
    toast_delete_fail: 'Xóa thất bại',
    regions_found:     'vùng được phát hiện',
    pages_done:        'trang hoàn thành!',
    loaded_from_lib:   'Đã tải từ thư viện',
    reading_file:      'Đang đọc',
    toast_run_ocr_first: 'Hãy chạy OCR cho tài liệu này trước.',
    toast_loaded_saved:  'Đã tải kết quả đã lưu',
    badge_text:          'Đã OCR',
    badge_translated:    'Đã dịch',
    badge_summarized:    'Đã tóm tắt',
  },

  // ── English ────────────────────────────────────────────
  en: {
    app_name:          'SmartDocs Platform',
    app_tagline:       'AI Document Platform',

    nav_home:          '🏠 Home',
    nav_ocr:           '🔍 OCR',
    nav_correct:       '✏️ Correct',
    nav_translate:     '🌐 Translate',
    nav_summarize:     '📝 Summarize',
    nav_documents:     '📁 Documents',
    nav_admin:         '⚙️ Admin',
    nav_settings:      '⚙ Settings',
    nav_sign_out:      '⏏ Sign Out',

    // Settings (cloud keys + privacy)
    settings_privacy_title: '🔒 Privacy — where AI processing happens',
    settings_privacy_desc:  '“Allow cloud processing” lets AI features send document text, retrieval excerpts and prompts to a configured cloud provider. “Local only” keeps everything on this machine (offline translation, local models).',
    settings_keys_title:    '🔑 Cloud provider API keys',
    settings_keys_desc:     'Keys are stored in your operating system’s credential store (macOS Keychain / Windows Credential Manager / Linux Secret Service) — never in files or the database. Only the last 4 characters are ever shown.',
    settings_loading:       'Loading…',
    settings_mode_local:    '🔒 Local only — nothing is sent to the cloud',
    settings_mode_cloud:    '☁ Cloud processing allowed',
    settings_enable_cloud:  'Allow cloud processing…',
    settings_disable_cloud: 'Switch to Local only',
    settings_env_locked:    'Set by ALLOW_CLOUD in .env — remove it there to control this here.',
    settings_cloud_on:      'Cloud processing allowed.',
    settings_cloud_off:     'Local only enabled — nothing leaves this machine.',
    settings_state_none:        'Not configured',
    settings_state_configured:  'Configured',
    settings_state_testing:     'Testing…',
    settings_state_connected:   'Connected',
    settings_state_invalid:     'Invalid key',
    settings_state_error:       'Unreachable',
    settings_state_unavailable: 'Credential store unavailable',
    settings_state_blocked:     'Local only',
    settings_keyring_unavailable: 'The OS credential store is unavailable — keys cannot be saved here. ',
    settings_local_only_keys: 'Local only is enabled — cloud keys are not used or validated in this mode.',
    settings_from_env:      'from .env',
    settings_env_key:       'This key comes from .env and wins over a stored key.',
    settings_btn_save:      'Save',
    settings_btn_test:      'Test',
    settings_btn_remove:    'Remove',
    settings_key_enter:     'Paste API key…',
    settings_key_replace:   'Enter a new key to replace…',
    settings_key_required:  'Enter an API key first.',
    settings_key_saved:     'Key stored in the OS credential store.',
    settings_key_removed:   'Key removed.',
    settings_key_remove_confirm: 'Remove the stored API key for this provider?',
    settings_save_failed:   'Could not save.',
    settings_load_failed:   'Could not load settings.',
    engine_local_only:      '🔒 Local only — offline translation (see Settings)',

    home_hero_title:   'AI Document Platform',
    home_hero_sub:     'Extract, correct, translate and summarize text from images, PDFs and documents.',

    tc_ocr_title:      'OCR Extract',
    tc_ocr_desc:       'Extract text from images and PDFs with bounding box visualization and confidence scores.',
    tc_correct_title:  'Correct Text',
    tc_correct_desc:   'Fix OCR mistakes, spelling errors, grammar issues and formatting automatically.',
    tc_translate_title:'Translate',
    tc_translate_desc: 'Translate text between languages with auto-detection. EN ↔ VI and more.',
    tc_summarize_title:'Summarize',
    tc_summarize_desc: 'Generate short summaries, bullet points or executive summaries from any text.',
    tc_documents_title:'Documents',
    tc_documents_desc: 'Manage, re-open and download your documents and saved OCR results.',
    tc_chat_title:     'SmartDocs AI',
    tc_chat_desc:      'Chat with AI — general Q&A or ask questions grounded in a single document.',
    tc_agent_title:    'Agent',
    tc_agent_desc:     'Autonomous assistant that orchestrates multiple tools to complete complex tasks.',
    tc_admin_title:    'Admin',
    tc_admin_desc:     'Manage users, monitor activity and configure the system.',
    get_started:       'Get Started →',

    ocr_extract:       'OCR Extract',
    ocr_upload_hint:   'Upload an image or PDF to extract text',
    ocr_drop_hint:     'Drop file here or',
    ocr_drop_full:     'Drop file here or <span style="color:var(--accent2)">click to browse</span>',
    ocr_click_browse:  'click to browse',
    ocr_file_formats:  'JPG · PNG · WEBP · PDF (multi-page)',
    run_ocr:           '▶ Run OCR',
    ocr_all:           '⚡ OCR All',
    ocr_reset:         '↩ Reset',
    ocr_file_label:    'File',
    ocr_summary:       'Summary',
    ocr_regions:       'Regions',
    ocr_avg_conf:      'Avg Conf',
    ocr_time:          'Time',
    ocr_pages:         'Pages',
    ocr_extracted_text:'Extracted Text',
    ocr_detections:    'Detections',
    ocr_copy:          '📋 Copy',
    ocr_dl_txt:        '⬇ TXT',
    ocr_dl_md:         '⬇ MD',
    ocr_dl_json:       '⬇ JSON',
    ocr_tab_md:        '📝 Markdown',
    ocr_tab_raw:       '⟨⟩ Raw',
    ocr_tab_images:    '🖼 Images',
    ocr_tab_json:      '{ } JSON',
    ocr_select_region: '🔳 Select Region',
    ocr_send_to:       'Send To',
    send_correct:      '→ Correct',
    send_translate:    '→ Translate',
    send_summarize:    '→ Summarize',
    run_ocr_running:   'Running…',
    ocr_all_running:   'All pages…',
    ocr_empty:         'Run OCR to see results',
    ocr_layout_label:  'Layout:',
    ocr_layout_original: 'Original',
    ocr_layout_enhanced: '✨ Enhanced',
    ocr_engine_label:  'Engine:',
    ocr_engine_recommended: '⭐ Recommended',
    ocr_engine_vietnamese:  '🇻🇳 Vietnamese',
    ocr_engine_standard:    '📄 Standard',
    ocr_ai_label:      'AI Cleanup:',
    ocr_ai_off:        'Off',
    ocr_ai_on:         '🧠 On',
    ocr_mode_standard: '📄 Standard',
    ocr_mode_smart:    '🧠 Smart OCR',
    ocr_mode_tooltip:  'Standard: standard OCR. Smart: OCR + AI enhancement (coming soon)',

    correct_title:     'Correct Text',
    correct_result:    'Result',
    correct_paste:     'Paste',
    correct_upload:    'Upload',
    correct_placeholder:'Paste text to correct…',
    correct_run:       '✨ Correct Text',
    correct_running:   'Correcting…',
    correct_empty:     'Corrected text will appear here',
    correct_import:    '📥 Import from OCR',
    send_to:           'Send To',

    translate_title:   'Translate',
    translate_result:  'Translation',
    translate_input_label: 'Input',
    translate_placeholder: 'Enter text to translate…',
    translate_run:     '🌐 Translate',
    translate_running: 'Translating…',
    translate_empty:   'Translation will appear here',
    translate_import:  '📥 Import from OCR',
    translate_engine:  'Translation Engine',
    engine_auto:       '⚡ Auto',
    engine_recommended:'Recommended',
    engine_online:     '🌐 Online',
    engine_offline:    '📴 Offline',
    engine_checking:   'Checking…',
    auto_detect:       'Auto Detect',
    engine_no_internet:      'No Internet connection',
    engine_warn_online_no_net: 'Online mode requires an Internet connection.',
    engine_warn_offline_missing: 'Offline engine is not installed.',
    engine_online_required:  'Online mode requires Internet.',
    engine_used_online:  'Google Translate',
    engine_used_offline: 'Offline Translation',
    engine_used_auto:    'Auto',
    engine_fallback:     'Fallback',
    engine_rechecking:       'Rechecking connection…',
    engine_internet_restored: 'Network detected. Checking…',
    engine_internet_back:    'Internet connection restored! Online mode is ready.',
    engine_disabled_click:   'Click to re-check connection',
    lang_vi:           'Vietnamese',
    lang_en:           'English',
    lang_zh:           'Chinese',
    lang_ja:           'Japanese',
    lang_ko:           'Korean',
    lang_fr:           'French',
    lang_de:           'German',
    lang_es:           'Spanish',

    // Chat history panel (persistence)
    'chat.history':       'Conversation history',
    'chat.new':           'New chat',
    'chat.history_empty': 'No conversations yet.',
    'chat.general_group': 'General Assistant',
    'chat.rename':        'Rename',
    'chat.delete':        'Delete',
    'chat.need_doc':      'Open a document conversation or switch to General Assistant.',
    'chat.view_doc':      'View document',
    doc_not_found:        'Document not found',
    'nav.back':           'Back',

    summarize_title:   'Summarize',
    summarize_result:  'Summary',
    summarize_placeholder:'Paste text to summarize…',
    summarize_mode:    'Summary Mode',
    mode_short:        '📄 Short',
    mode_bullets:      '• Bullet Points',
    mode_executive:    '📊 Executive',
    summarize_run:     '📝 Summarize',
    summarize_running: 'Summarizing…',
    summarize_empty:   'Summary will appear here',
    summarize_import:  '📥 Import from OCR',
    // Engine selector (Fast mode)
    sum_engine_label:  'Summary Engine',
    sum_engine_auto:   '⚡ Auto',
    sum_engine_fast:   'Fast',
    sum_engine_smart:  'Smart (VI)',
    sum_engine_rec:    'Recommended',
    engine_recommended:'Recommended',
    // Dual-mode selector
    sum_mode_label:    'Summary Mode',
    sum_mode_fast:     'Fast Summary',
    sum_mode_fast_rec: 'Recommended',
    sum_mode_ai:       'AI Rewrite',
    // AI status
    sum_ai_checking:   'Checking…',
    sum_ai_loading:    'Loading AI model…',
    sum_ai_ready:      '🧠 AI · Ready',
    sum_ai_ready_word: 'Ready',
    sum_ai_api:        '🌐 API · Ready',
    sum_ai_unavailable:'AI unavailable — will use Fast',
    // Output style pill labels
    mode_short_lbl:    'Short',
    mode_bullets_lbl:  'Bullets',
    mode_exec_lbl:     'Executive',

    docs_title:        '📁 Documents',
    docs_sub:          'Manage your uploaded files',
    docs_refresh:      '↻ Refresh',
    docs_all:          'All',
    docs_images:       '🖼 Images',
    docs_pdfs:         '📜 PDFs',
    docs_text:         '📄 Text',
    docs_search:       'Search files…',
    docs_col_file:     'File',
    docs_col_type:     'Type',
    docs_col_size:     'Size',
    docs_col_owner:    'Owner',
    docs_col_uploaded: 'Uploaded',
    docs_col_status:   'Status',
    docs_col_actions:  'Actions',
    docs_empty:        'No documents yet. Upload a file to get started.',
    docs_loading:      'Loading…',
    pagination_showing: 'Showing',
    pagination_of:      'of',
    pagination_items:   'files',
    docs_delete_confirm: 'Delete this document? This cannot be undone.',
    docs_deleted:      'Deleted',
    // Docs stats chips
    docs_stat_total:   'Total',
    docs_stat_images:  'Images',
    docs_stat_pdfs:    'PDFs',
    docs_stat_texts:   'Text files',
    // Docs action tooltips
    docs_tip_ocr:      'Run OCR',
    docs_tip_correct:  'Correct Text',
    docs_tip_translate:'Translate',
    docs_tip_summarize:'Summarize',
    docs_tip_download: 'Download',
    docs_tip_delete:   'Delete',
    // Translate engine status
    engine_status_all:    '🟢 Online + Offline ready',
    engine_status_online: '🌐 Online ready',
    engine_status_offline:'📴 Offline only',
    engine_status_none:   '⚠️ No engine available',
    engine_status_error:  '⚠️ Status unavailable',
    engine_offline_tip:   'Offline translation unavailable',
    engine_online_tip:    'No internet connection',
    // File loaded
    toast_file_loaded: 'Loaded',

    upload_txt_docx_pdf: 'Upload TXT / DOCX / PDF',

    copy:              '📋 Copy',
    download_txt:      '⬇ TXT',
    copied:            'Copied!',
    copy_failed:       'Failed to copy',
    copy_nothing:      'Nothing to copy',
    loading:           'Loading…',
    cancel:            'Cancel',
    paste_tab:         'Paste',
    upload_tab:        'Upload',

    toast_text_copied: 'Text copied!',
    toast_region_copied: 'Text in selected region copied!',
    toast_unsupported: 'Unsupported file type',
    toast_no_text:     'Please enter or import text first.',
    toast_no_ocr:      'No OCR result to import. Run OCR first.',
    toast_ocr_imported:'OCR text imported!',
    toast_no_output:   'No output to send',
    toast_correct_done:'Text corrected!',
    toast_translate_done:'Translation complete!',
    toast_summarize_done:'Summary ready!',
    toast_load_fail:   'Failed to load documents',
    toast_read_fail:   'Could not read file: ',
    toast_imported:    'Text imported!',
    toast_delete_fail: 'Delete failed',
    regions_found:     'regions found',
    pages_done:        'pages done!',
    loaded_from_lib:   'Loaded from library',
    reading_file:      'Reading',
    toast_run_ocr_first: 'Run OCR on this document first.',
    toast_loaded_saved:  'Loaded saved result',
    badge_text:          'OCR',
    badge_translated:    'Translated',
    badge_summarized:    'Summarized',
  }
};

// ── Core i18n engine ────────────────────────────────────────
const I18n = {
  _lang: null,
  _STORAGE_KEY: 'smartdocs_lang',
  _SUPPORTED: ['vi', 'en'],
  _DEFAULT: 'vi',

  /** Get current language code */
  get lang() { return this._lang || this._DEFAULT; },

  /** Initialize: load from localStorage or default */
  init() {
    const saved = localStorage.getItem(this._STORAGE_KEY);
    this._lang = this._SUPPORTED.includes(saved) ? saved : this._DEFAULT;
    this._applyToDOM();
    this._updateSelector();
  },

  /** Translate a key, with optional fallback */
  t(key, fallback) {
    const dict = TRANSLATIONS[this.lang] || TRANSLATIONS[this._DEFAULT];
    return dict[key] ?? TRANSLATIONS[this._DEFAULT][key] ?? fallback ?? key;
  },

  /** Switch to a new language and re-render */
  setLang(code) {
    if (!this._SUPPORTED.includes(code)) return;
    this._lang = code;
    localStorage.setItem(this._STORAGE_KEY, code);
    // Sync with server session (best-effort)
    fetch('/api/set-lang', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lang: code })
    }).catch(() => {});
    this._applyToDOM();
    this._updateSelector();
    this._updateDynamicText();
  },

  /** Apply data-i18n attributes across the whole document */
  _applyToDOM() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.dataset.i18n;
      const val = this.t(key);
      // Allow inner HTML (for elements with child spans) vs text-only
      if (el.dataset.i18nHtml !== undefined) {
        el.innerHTML = val;
      } else {
        el.textContent = val;
      }
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      el.placeholder = this.t(el.dataset.i18nPlaceholder);
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
      el.title = this.t(el.dataset.i18nTitle);
    });
    // Update page <title>
    document.title = `${this.t('app_name')} — AI`;
    // Update html lang attr
    document.documentElement.lang = this._lang;
  },

  /** Sync the selector buttons in the navbar */
  _updateSelector() {
    document.querySelectorAll('.lang-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.lang === this._lang);
    });
  },

  /** Update any text that was set dynamically by JS (not via data-i18n) */
  _updateDynamicText() {
    // Mode pills
    const modeMap = { short: 'mode_short', bullets: 'mode_bullets', executive: 'mode_executive' };
    document.querySelectorAll('.mode-pill').forEach(p => {
      const key = modeMap[p.dataset.mode];
      if (key) p.textContent = this.t(key);
    });
    // Filter pills for docs
    const filterMap = { all: 'docs_all', image: 'docs_images', pdf: 'docs_pdfs', text: 'docs_text' };
    document.querySelectorAll('.filter-pill').forEach(p => {
      const key = filterMap[p.dataset.filter];
      if (key) p.textContent = this.t(key);
    });
  }
};

// Shorthand
function t(key, fallback) { return I18n.t(key, fallback); }
