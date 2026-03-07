// State Management
const state = {
    userId: null,
    token: localStorage.getItem('chat_token'),
    user: null, 
    conversationId: null,
    messages: [],
    isDeepThinking: false,
    isWebSearch: false,
    currentView: 'chat', // 'chat', 'kb', 'wechat', 'settings', 'agent-config'
    kbFiles: [],
    wechatConfigs: [],
    currentWechatConfig: null,
    agentOpeningEnabled: true  // 开场白开关状态
};

// DOM Elements
const elements = {
    chatView: document.getElementById('chat-view'),
    kbView: document.getElementById('kb-view'),
    wechatView: document.getElementById('wechat-view'),
    settingsView: document.getElementById('settings-view'),
    userListView: document.getElementById('user-list-view'),
    settingsContainer: document.getElementById('settings-container'),
    chatContainer: document.getElementById('chat-container'),
    welcomeScreen: document.getElementById('welcome-screen'),
    chatInput: document.getElementById('chat-input'),
    sendBtn: document.getElementById('send-btn'),
    historyList: document.getElementById('history-list'),
    imagePreview: document.getElementById('image-preview-area'),
    imageUpload: document.getElementById('image-upload'),
    btnDeepThinking: document.getElementById('btn-deep-thinking'),
    btnWebSearch: document.getElementById('btn-web-search'),
    kbFileList: document.getElementById('kb-file-list'),
    wechatConfigList: document.getElementById('wechat-config-list'),
    uploadModal: document.getElementById('upload-modal'),
    wechatConfigModal: document.getElementById('wechat-config-modal'),
    kbFilePreview: document.getElementById('kb-file-preview'),
    loginModal: document.getElementById('login-modal'),
    authForm: document.getElementById('auth-form'),
    authEmail: document.getElementById('auth-email'),
    authUsername: document.getElementById('auth-username'),
    authPassword: document.getElementById('auth-password'),
    authBtn: document.getElementById('auth-btn'),
    usernameGroup: document.getElementById('username-group'),
    authTitle: document.getElementById('auth-title'),
    authToggleText: document.getElementById('auth-toggle-text'),
    authToggleLink: document.getElementById('auth-toggle-link'),
    agentConfigView: document.getElementById('agent-config-view'),
    kbUploadBtn: document.getElementById('kb-upload-btn')
};

let currentImage = null;
let pendingUploads = [];
let isRegisterMode = false;
let msgIdCounter = 0;

// --- Mobile Sidebar Control ---
function openSidebar() {
    document.getElementById('sidebar').classList.add('open');
    document.getElementById('sidebar-overlay').classList.add('open');
    document.body.style.overflow = 'hidden';
}

function closeSidebar() {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebar-overlay').classList.remove('open');
    document.body.style.overflow = '';
}

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();

    // 回车键发送消息（Shift+Enter 换行）
    elements.chatInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
});

async function createConversation() {
    try {
        const res = await fetch('/api/conversations', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${state.token}`
            },
            body: JSON.stringify({ user_id: state.userId })
        });
        if (res.ok) {
            const data = await res.json();
            return data.conversation_id;
        }
    } catch (e) {
        console.error("Failed to create conversation", e);
    }
    return null;
}

async function checkAuth() {
    if (state.token) {
        try {
            const res = await fetch('/api/users/me', {
                headers: { 'Authorization': `Bearer ${state.token}` }
            });
            if (res.ok) {
                const user = await res.json();
                state.user = user;
                state.userId = user.id;

                // 所有用户都显示系统配置按钮
                const settingsBtn = document.getElementById('settings-btn');
                if (settingsBtn) {
                    settingsBtn.style.display = '';
                }
                // 管理员显示用户列表按钮
                const userListBtn = document.getElementById('user-list-btn');
                if (userListBtn) {
                    userListBtn.style.display = user.role === 'admin' ? '' : 'none';
                }
                
                let savedId = localStorage.getItem('current_conversation_id');
                if (savedId && isNaN(parseInt(savedId))) {
                    savedId = null; 
                }

                if (savedId) {
                    state.conversationId = parseInt(savedId);
                } else {
                    // 不自动创建会话，等用户发消息时再创建
                    state.conversationId = null;
                }

                // 切换侧边栏底部为已登录状态
                document.getElementById('footer-logged-in').style.display = 'block';
                document.getElementById('footer-logged-out').style.display = 'none';
                document.getElementById('user-display-name').textContent = user.username || user.email;
                document.getElementById('user-display-email').textContent = user.email;

                elements.loginModal.style.display = 'none';
                initializeApp();
                return;
            }
        } catch (e) {
            console.error("Auth check failed", e);
        }
    }
    localStorage.removeItem('chat_token');
    // 检查是否是退出后刷新，显示对应提示
    const wasLoggedOut = sessionStorage.getItem('logged_out');
    const authTitle = document.getElementById('auth-title');
    if (wasLoggedOut && authTitle) {
        authTitle.textContent = '您已退出登录，请重新登录。';
        sessionStorage.removeItem('logged_out');
    }
    elements.loginModal.style.display = 'flex';
}

function initializeApp() {
    loadHistory();
    // 如果有当前会话，加载其历史消息
    if (state.conversationId) {
        loadConversation(state.conversationId);
    }
    // 加载开场白，动态替换欢迎语
    loadOpeningMessage();
    elements.chatInput.focus();
}

// --- Auth Logic ---

function toggleAuthMode() {
    isRegisterMode = !isRegisterMode;
    if (isRegisterMode) {
        elements.authTitle.textContent = "创建新账号";
        elements.usernameGroup.style.display = 'block';
        elements.authUsername.required = true;
        elements.authBtn.textContent = "注册";
        elements.authToggleText.textContent = "已有账号？";
        elements.authToggleLink.textContent = "立即登录";
    } else {
        elements.authTitle.textContent = "欢迎回来！请登录以继续。";
        elements.usernameGroup.style.display = 'none';
        elements.authUsername.required = false;
        elements.authBtn.textContent = "登录";
        elements.authToggleText.textContent = "还没有账号？";
        elements.authToggleLink.textContent = "立即注册";
    }
}

async function handleAuthSubmit(e) {
    e.preventDefault();
    const email = elements.authEmail.value.trim();
    const password = elements.authPassword.value.trim();
    const username = elements.authUsername.value.trim();
    
    const originalText = elements.authBtn.textContent;
    elements.authBtn.textContent = "处理中...";
    elements.authBtn.disabled = true;

    try {
        if (isRegisterMode) {
            const res = await fetch('/api/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password, username })
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || "注册失败");
            }
            alert("注册成功！请登录。");
            toggleAuthMode();
        } else {
            const res = await fetch('/api/token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || "登录失败");
            }
            const data = await res.json();
            localStorage.setItem('chat_token', data.access_token);
            state.token = data.access_token;
            await checkAuth();
        }
    } catch (err) {
        alert(err.message);
    } finally {
        elements.authBtn.textContent = originalText;
        elements.authBtn.disabled = false;
    }
}

// --- Chat Logic ---

function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = textarea.scrollHeight + 'px';
    if (textarea.value === '') {
        textarea.style.height = 'auto';
    }
}

function toggleDeepThinking() {
    state.isDeepThinking = !state.isDeepThinking;
    elements.btnDeepThinking.classList.toggle('active', state.isDeepThinking);
}

function toggleWebSearch() {
    state.isWebSearch = !state.isWebSearch;
    elements.btnWebSearch.classList.toggle('active', state.isWebSearch);
}

function triggerImageUpload() {
    elements.imageUpload.click();
}

function handleImageSelect(input) {
    if (input.files && input.files[0]) {
        const file = input.files[0];
        currentImage = file;
        document.getElementById('image-name').textContent = file.name;
        elements.imagePreview.style.display = 'flex';
    }
}

function clearImage() {
    currentImage = null;
    elements.imageUpload.value = '';
    elements.imagePreview.style.display = 'none';
}

async function sendMessage() {
    const text = elements.chatInput.value.trim();
    if (!text && !currentImage) return;

    console.log("[DEBUG] 开始发送消息，text:", text, "hasImage:", !!currentImage);
    elements.welcomeScreen.style.display = 'none';

    // ★ 如果不是联网搜索模式，关闭搜索面板
    if (!state.isWebSearch) {
        console.log("[DEBUG] 非联网搜索模式，关闭搜索面板");
        closeSearchPanel();
    }

    // 没有会话时，发消息前先创建
    if (!state.conversationId) {
        state.conversationId = await createConversation();
        if (state.conversationId) {
            localStorage.setItem('current_conversation_id', state.conversationId);
            loadHistory();
        } else {
            return;
        }
    }

    // ★ 添加用户消息到 UI（保存引用以防被覆盖）
    console.log("[DEBUG] 正在将用户消息添加到 UI");
    const userMsgId = addMessageToUI('user', text, currentImage ? URL.createObjectURL(currentImage) : null);
    
    elements.chatInput.value = '';
    elements.chatInput.style.height = 'auto';
    const imageToSend = currentImage;
    clearImage();

    const formData = new FormData();
    formData.append('query', text);
    formData.append('user_id', state.userId);
    formData.append('conversation_id', state.conversationId);
    formData.append('deep_thinking', state.isDeepThinking);
    formData.append('web_search', state.isWebSearch);
    
    if (imageToSend) {
        formData.append('image', imageToSend);
    }

    // ★ 添加 bot 的"思考中"消息
    console.log("[DEBUG] 添加 bot 思考中状态");
    const loadingId = addMessageToUI('bot', '<i class="fas fa-circle-notch fa-spin"></i> 思考中...', null, true);

    try {
        const response = await fetch('/api/langgraph/query', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${state.token}`
            },
            body: formData
        });

        if (!response.ok) throw new Error('Network response was not ok');

        const contentType = response.headers.get("Content-Type");
        if (contentType && contentType.includes("text/event-stream")) {
            console.log("[DEBUG] 收到 SSE 流式响应");
            // ★ 先不清空，等收到第一个数据块再清空
            const reader = response.body.getReader();
            if (!reader) throw new Error("无法读取响应流");
            await readStream(reader, loadingId);
        } else {
            console.log("[DEBUG] 收到普通 JSON 响应");
            const data = await response.json();
            updateMessageUI(loadingId, data.answer || data.response || "No response");
        }

        // 更新侧边栏历史列表
        loadHistory();

    } catch (error) {
        updateMessageUI(loadingId, '⚠️ 出错啦: ' + error.message);
    }
}

async function readStream(reader, messageId) {
    const decoder = new TextDecoder();
    let accumulatedContent = "";
    let firstChunk = true;
    
    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n\n');
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const jsonStr = line.substring(6);
                        if (jsonStr.trim() === "[DONE]") continue;
                        
                        const parsed = JSON.parse(jsonStr);
                        
                        if (typeof parsed === 'object' && parsed.interruption) {
                            console.log("Interruption detected");
                        } else if (typeof parsed === 'object' && parsed.search_results) {
                            // ★ 收到搜索结果，展示在右侧面板
                            showSearchResults(parsed.search_results);
                        } else if (typeof parsed === 'object' && parsed.generated_image) {
                            // ★ 收到生成的图片，先清空 loading，再追加图片
                            if (firstChunk) {
                                updateMessageUI(messageId, "");
                                firstChunk = false;
                            }
                            appendGeneratedImage(messageId, parsed.generated_image);
                        } else {
                            // ★ 收到第一个数据块时清空"思考中"
                            if (firstChunk) {
                                updateMessageUI(messageId, "");
                                firstChunk = false;
                            }
                            accumulatedContent += parsed;
                            updateMessageUI(messageId, accumulatedContent);
                        }
                    } catch (e) {
                       console.warn("Failed to parse SSE data:", line, e);
                    }
                }
            }
        }
        
        // ★ 如果流结束了但没有收到任何内容，显示默认消息
        if (firstChunk) {
            updateMessageUI(messageId, accumulatedContent || "暂无回复");
        }
    } catch (e) {
        console.error("Stream reading error:", e);
        throw e;
    }
}

// ★ 联网搜索结果面板
function showSearchResults(results) {
    const panel = document.getElementById('search-results-panel');
    const list = document.getElementById('search-results-list');
    if (!panel || !list) return;

    list.innerHTML = '';
    if (!results || results.length === 0) {
        list.innerHTML = '<div style="color:#999;padding:16px;">未找到相关搜索结果</div>';
    } else {
        results.forEach((r, i) => {
            const item = document.createElement('a');
            item.className = 'search-result-item';
            item.href = r.url;
            item.target = '_blank';
            item.rel = 'noopener noreferrer';
            item.innerHTML = `
                <div class="search-result-index">${i + 1}</div>
                <div class="search-result-body">
                    <div class="search-result-title">${escapeHtml(r.title || '无标题')}</div>
                    <div class="search-result-snippet">${escapeHtml(r.snippet || '')}</div>
                    <div class="search-result-url">${escapeHtml(r.url || '')}</div>
                </div>
            `;
            list.appendChild(item);
        });
    }
    panel.classList.add('open');
}

// ★ 在消息气泡中追加生成的图片
function appendGeneratedImage(messageId, imageUrl) {
    const fullUrl = imageUrl.startsWith('http') ? imageUrl : (window.location.origin + imageUrl);
    const msgEl = document.getElementById(messageId);
    if (!msgEl) return;
    const contentEl = msgEl.querySelector('.msg-content') || msgEl;

    // 图片容器：独占一行，在文字下方
    const wrapper = document.createElement('div');
    wrapper.style.cssText = 'display:block; margin-top:12px; line-height:0;';

    const img = document.createElement('img');
    img.src = fullUrl;
    img.alt = 'AI 生成图片';
    img.style.cssText = 'max-width:320px; width:100%; border-radius:10px; cursor:zoom-in; display:block;';
    img.onclick = () => openImageLightbox(fullUrl);

    wrapper.appendChild(img);
    contentEl.appendChild(wrapper);
    msgEl.closest('.chat-container, #chatContainer') && (msgEl.closest('.chat-container, #chatContainer').scrollTop = 99999);
}

function openImageLightbox(url) {
    let lb = document.getElementById('imageLightbox');
    if (!lb) {
        lb = document.createElement('div');
        lb.id = 'imageLightbox';
        lb.style.cssText = 'display:none;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.85);align-items:center;justify-content:center;';
        lb.innerHTML = `
            <div style="position:relative;max-width:90vw;max-height:90vh;">
                <img id="lightboxImg" src="" style="max-width:90vw;max-height:85vh;border-radius:12px;display:block;object-fit:contain;">
                <button onclick="closeImageLightbox()" style="position:absolute;top:-14px;right:-14px;width:32px;height:32px;border-radius:50%;border:none;background:#fff;color:#333;font-size:18px;cursor:pointer;line-height:1;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,0.3);">✕</button>
            </div>`;
        lb.onclick = (e) => { if (e.target === lb) closeImageLightbox(); };
        document.body.appendChild(lb);
    }
    document.getElementById('lightboxImg').src = url;
    lb.style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

function closeImageLightbox() {
    const lb = document.getElementById('imageLightbox');
    if (lb) { lb.style.display = 'none'; document.body.style.overflow = ''; }
}

function closeSearchPanel() {
    const panel = document.getElementById('search-results-panel');
    if (panel) panel.classList.remove('open');
}

// --- UI Helpers ---

function addMessageToUI(type, content, imageUrl, isLoading = false) {
    console.log("[DEBUG] addMessageToUI 调用:", {type, contentSnippet: content.substring(0, 30), isLoading});
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${type}`;
    const id = 'msg-' + Date.now() + '-' + (++msgIdCounter);
    msgDiv.id = id;

    let innerContent = '';
    if (imageUrl) {
        innerContent += `<img src="${imageUrl}" style="max-width: 300px; border-radius: 8px; margin-bottom: 8px; display: block;">`;
    }
    
    let parsedContent = '';
    try {
        parsedContent = isLoading ? content : (typeof marked !== 'undefined' ? marked.parse(content) : content);
    } catch (e) {
        console.error("[ERROR] Markdown 解析失败:", e);
        parsedContent = content; // 回退到原始内容
    }

    msgDiv.innerHTML = `
        <div class="avatar ${type}">
            ${type === 'user' ? '<i class="fas fa-user"></i>' : '<span style="color:#4d6bfe">🐋</span>'}
        </div>
        <div class="msg-content markdown-body">${innerContent}${parsedContent}</div>
    `;

    if (!elements.chatContainer) {
        console.error("[ERROR] elements.chatContainer 丢失，正在尝试重新获取");
        elements.chatContainer = document.getElementById('chat-container');
    }

    if (elements.chatContainer) {
        elements.chatContainer.appendChild(msgDiv);
        elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
    } else {
        console.error("[ERROR] 无法将消息添加到 UI，chat-container 元素无法定位");
    }
    
    if (!isLoading) {
        msgDiv.querySelectorAll('pre code').forEach((block) => {
            hljs.highlightElement(block);
        });
    }

    return id;
}

function updateMessageUI(id, newContent) {
    const msgDiv = document.getElementById(id);
    if (msgDiv) {
        const contentDiv = msgDiv.querySelector('.msg-content');
        contentDiv.innerHTML = marked.parse(newContent);
        msgDiv.querySelectorAll('pre code').forEach((block) => {
            hljs.highlightElement(block);
        });
        elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
    }
}

// --- Sidebar & Navigation ---

async function startNewChat() {
    const newId = await createConversation();
    if (newId) {
        state.conversationId = newId;
        localStorage.setItem('current_conversation_id', state.conversationId);
        
        // 移动端：关闭侧边栏
        closeSidebar();
        // 关闭搜索面板
        closeSearchPanel();
        
        // 安全取出 welcomeScreen 再清空
        if (elements.welcomeScreen.parentNode) {
            elements.welcomeScreen.parentNode.removeChild(elements.welcomeScreen);
        }
        elements.chatContainer.innerHTML = '';
        elements.chatContainer.appendChild(elements.welcomeScreen);
        elements.welcomeScreen.style.display = 'flex';
        
        showChatView();
        loadHistory();
    } else {
        alert("创建新会话失败，请重试");
    }
}

async function loadHistory() {
    try {
        const res = await fetch(`/api/conversations/user/${state.userId}`, {
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const threads = await res.json();
        
        elements.historyList.innerHTML = '';
        if (threads.length === 0) {
            elements.historyList.innerHTML = '<div style="padding:10px; color:#666; font-size:12px;">暂无历史记录</div>';
            return;
        }

        threads.forEach(thread => {
            const threadId = thread.thread_id || thread.id || '';
            const label = thread.summary || thread.title || `对话 ${String(threadId).substring(0,8)}...`;
            
            const div = document.createElement('div');
            div.className = 'history-item';
            if (threadId == state.conversationId) div.classList.add('active');

            // 会话标题
            const labelSpan = document.createElement('span');
            labelSpan.className = 'history-label';
            labelSpan.innerHTML = `<i class="far fa-comment-alt"></i> ${label}`;
            labelSpan.style.cssText = 'flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; cursor:pointer;';
            labelSpan.onclick = () => loadConversation(threadId);

            // 删除按钮
            const delBtn = document.createElement('span');
            delBtn.className = 'history-delete-btn';
            delBtn.innerHTML = '<i class="fas fa-trash-alt"></i>';
            delBtn.title = '删除会话';
            delBtn.style.cssText = 'color:#666; cursor:pointer; padding:2px 6px; font-size:12px; flex-shrink:0; display:none;';
            delBtn.onclick = (e) => {
                e.stopPropagation();
                deleteConversation(threadId);
            };

            div.style.cssText = 'display:flex; align-items:center; gap:4px;';
            div.onmouseenter = () => { delBtn.style.display = 'inline'; };
            div.onmouseleave = () => { delBtn.style.display = 'none'; };

            div.appendChild(labelSpan);
            div.appendChild(delBtn);
            elements.historyList.appendChild(div);
        });
    } catch (e) {
        console.error("Load history failed", e);
    }
}

async function deleteConversation(threadId) {
    if (!confirm('确定要删除该会话吗？')) return;
    try {
        const res = await fetch(`/api/conversations/${threadId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
        if (!res.ok) throw new Error('删除失败');
        
        // 如果删除的是当前会话，切换到新会话
        if (threadId == state.conversationId) {
            state.conversationId = await createConversation();
            if (state.conversationId) {
                localStorage.setItem('current_conversation_id', state.conversationId);
            }
            elements.chatContainer.innerHTML = '';
            elements.chatContainer.appendChild(elements.welcomeScreen);
            elements.welcomeScreen.style.display = 'flex';
        }
        loadHistory();
    } catch (e) {
        alert('删除会话失败: ' + e.message);
    }
}

async function loadConversation(threadId) {
    state.conversationId = threadId;
    localStorage.setItem('current_conversation_id', threadId);
    
    // 移动端：点击历史记录后关闭侧边栏
    closeSidebar();
    
    // 先把 welcomeScreen 安全取出（避免 innerHTML='' 时丢失引用）
    if (elements.welcomeScreen.parentNode) {
        elements.welcomeScreen.parentNode.removeChild(elements.welcomeScreen);
    }
    elements.welcomeScreen.style.display = 'none';
    
    // 清空聊天区域
    elements.chatContainer.innerHTML = '';

    try {
        const res = await fetch(`/api/conversations/${threadId}/messages?user_id=${state.userId}`, {
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
        
        if (!res.ok) throw new Error('加载消息失败');
        
        const messages = await res.json();
        
        if (messages.length === 0) {
            elements.chatContainer.appendChild(elements.welcomeScreen);
            elements.welcomeScreen.style.display = 'flex';
        } else {
            messages.forEach(msg => {
                const type = msg.sender === 'user' ? 'user' : 'bot';
                // 用户消息：image_url 是上传的图片；bot 消息：image_url 是 AI 生成的图片
                const uploadedImg = (msg.sender === 'user' && msg.image_url)
                    ? (msg.image_url.startsWith('http') ? msg.image_url : window.location.origin + msg.image_url)
                    : null;
                const msgId = addMessageToUI(type, msg.content || '', uploadedImg);
                // bot 消息有 image_url 说明是 AI 生成图片，用浮窗方式追加
                if (msg.sender !== 'user' && msg.image_url) {
                    appendGeneratedImage(msgId, msg.image_url);
                }
            });
        }
    } catch (e) {
        console.error("Load conversation messages failed", e);
        elements.chatContainer.innerHTML = '<div style="padding:20px; color:#999; text-align:center;">加载消息失败</div>';
    }
    
    showChatView();
    loadHistory();
}

function logout() {
    if(confirm('确定要退出登录并清除本地数据吗？')) {
        document.getElementById('footer-logged-in').style.display = 'none';
        document.getElementById('footer-logged-out').style.display = 'block';
        sessionStorage.setItem('logged_out', '1');
        localStorage.clear();
        location.reload();
    }
}

// --- Knowledge Base Logic ---
let kbPollingInterval = null;

function toggleKnowledgeBase() {
    if (elements.kbView.classList.contains('hidden')) {
        elements.chatView.classList.add('hidden');
        elements.wechatView.classList.add('hidden');
        elements.settingsView.classList.add('hidden');
        if (elements.userListView) elements.userListView.classList.add('hidden');
        if (elements.agentConfigView) elements.agentConfigView.classList.add('hidden');
        elements.kbView.classList.remove('hidden');
        state.currentView = 'kb';
        closeSidebar();
        loadKbFiles().then(() => {
            // 如果有正在索引的文件，自动启动轮询
            const anyIndexing = state.kbFiles.some(f => f.status === 'indexing' || f.status === 'pending');
            if (anyIndexing) startKbPolling();
        });
    }
}

function showChatView() {
    elements.kbView.classList.add('hidden');
    elements.wechatView.classList.add('hidden');
    elements.settingsView.classList.add('hidden');
    if (elements.userListView) elements.userListView.classList.add('hidden');
    if (elements.agentConfigView) elements.agentConfigView.classList.add('hidden');
    elements.chatView.classList.remove('hidden');
    state.currentView = 'chat';
    stopKbPolling();
}

async function loadKbFiles(silent = false) {
    console.log("[DEBUG] 开始加载知识库文件列表, user_id:", state.userId);
    if (!silent) {
        elements.kbFileList.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#666;">加载中...</td></tr>';
    }
    
    try {
        const res = await fetch(`/api/knowledge-base/user/${state.userId}`, {
             headers: {'Authorization': `Bearer ${state.token}`}
        });
        if (!res.ok) throw new Error("API Error: " + res.status);
        state.kbFiles = await res.json();
        console.log("[DEBUG] 知识库文件列表获取完毕, 数量:", state.kbFiles.length);
        renderKbTable(state.kbFiles);
    } catch (e) {
        console.error("[ERROR] 加载知识库失败:", e);
        if (!silent) {
            elements.kbFileList.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#cf6679;">加载失败: ' + e.message + '</td></tr>';
        }
    }
}

function startKbPolling() {
    stopKbPolling();
    kbPollingInterval = setInterval(async () => {
        await loadKbFiles(true);
        const anyIndexing = state.kbFiles.some(f => f.status === 'indexing' || f.status === 'pending');
        if (!anyIndexing) {
            stopKbPolling();
        }
    }, 5000);
}

function stopKbPolling() {
    if (kbPollingInterval) {
        clearInterval(kbPollingInterval);
        kbPollingInterval = null;
    }
}

function renderKbTable(files) {
    console.log("[DEBUG] 正在渲染知识库表格, 文件数:", files.length);
    if (!elements.kbFileList) {
        console.error("[ERROR] elements.kbFileList 元素丢失，尝试重新获取");
        elements.kbFileList = document.getElementById('kb-file-list');
    }

    if (!files || files.length === 0) {
        elements.kbFileList.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#666;">暂无文档，请点击右上角导入。</td></tr>';
        return;
    }
    
    try {
        const html = files.map(file => {
            const isReady = file.status === 'success';
            const safeFileName = (file.original_name || "未命名").replace(/'/g, "\\'");
            const nameHtml = isReady
                ? `<a href="javascript:void(0)" onclick="viewKbChunks(${file.id}, '${safeFileName}')" style="color:#4d6bfe; text-decoration:none; cursor:pointer;" title="点击查看文本块内容"><i class="far fa-file-alt" style="margin-right:8px;"></i>${file.original_name}</a>`
                : `<span style="color:#999;"><i class="far fa-file-alt" style="margin-right:8px;"></i>${file.original_name}</span>`;
            const embeddingBadge = file.embedding_type === 'dashscope'
                ? `<span style="font-size:11px; padding:2px 7px; border-radius:4px; background:#1a3a2a; color:#4ade80; border:1px solid #4ade8055;">百炼</span>`
                : `<span style="font-size:11px; padding:2px 7px; border-radius:4px; background:#1a2a3a; color:#60a5fa; border:1px solid #60a5fa55;">${file.embedding_type || '本地'}</span>`;
            
            return `
            <tr>
                <td>${nameHtml}</td>
                <td>${formatSize(file.size || 0)}</td>
                <td>${getStatusBadge(file.status)}</td>
                <td>${embeddingBadge}</td>
                <td>${file.created_at ? new Date(file.created_at).toLocaleString('zh-CN') : '-'}</td>
                <td>
                    ${isReady ? `<button onclick="viewKbChunks(${file.id}, '${safeFileName}')" style="background:none; border:none; color:#4d6bfe; cursor:pointer; margin-right:8px;" title="查看内容"><i class="fas fa-eye"></i></button>` : ''}
                    <button onclick="deleteKbFile(${file.id})" style="background:none; border:none; color:#cf6679; cursor:pointer;" title="删除">
                        <i class="fas fa-trash"></i>
                    </button>
                </td>
            </tr>`;
        }).join('');
        elements.kbFileList.innerHTML = html;
        console.log("[DEBUG] 知识库表格渲染完成");
    } catch (e) {
        console.error("[ERROR] 知识库列表渲染崩溃:", e);
        elements.kbFileList.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#cf6679;">渲染失败，请检查控制台</td></tr>';
    }
}

function filterKbFiles(text) {
    if (!text) {
        renderKbTable(state.kbFiles);
        return;
    }
    const lower = text.toLowerCase();
    const filtered = state.kbFiles.filter(f => f.original_name.toLowerCase().includes(lower));
    renderKbTable(filtered);
}

// --- Upload Modal ---

function openUploadModal() {
    elements.uploadModal.classList.remove('hidden');
    pendingUploads = [];
    renderPreview();
}

function closeUploadModal() {
    elements.uploadModal.classList.add('hidden');
    pendingUploads = [];
}

function handleKbFileSelect(input) {
    if (input.files) {
        pendingUploads = [...pendingUploads, ...Array.from(input.files)];
        renderPreview();
    }
    input.value = '';
}

function renderPreview() {
    if (pendingUploads.length === 0) {
        elements.kbFilePreview.innerHTML = '<div style="text-align:center; color:#666; margin-top:10px;">未选择文件</div>';
        return;
    }
    elements.kbFilePreview.innerHTML = pendingUploads.map((file, idx) => `
        <div class="file-item">
            <span style="font-size:12px; color:#ccc;">${file.name}</span>
            <i class="fas fa-times" style="cursor:pointer; color:#999;" onclick="removePendingFile(${idx})"></i>
        </div>
    `).join('');
}

function removePendingFile(idx) {
    pendingUploads.splice(idx, 1);
    renderPreview();
}

async function uploadKbFiles() {
    if (pendingUploads.length === 0) return;
    
    console.log("[DEBUG] 开始上传选定的知识库文件, 数量:", pendingUploads.length);
    const btn = elements.kbUploadBtn;
    const originalHtml = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 上传中...';
    btn.disabled = true;

    try {
        for (const file of pendingUploads) {
            console.log("[DEBUG] 正在上传文件:", file.name);
            const formData = new FormData();
            formData.append('file', file);
            formData.append('user_id', state.userId);
            
            const res = await fetch('/api/upload', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${state.token}`
                },
                body: formData
            });

            if (!res.ok) {
                const errData = await res.json();
                throw new Error(errData.detail || "上传失败");
            }
        }
        
        console.log("[DEBUG] 所有文件上传并请求索引成功");
        closeUploadModal();
        alert('上传成功！后台正在建立索引，请稍候。');
        await loadKbFiles();
        startKbPolling();
        
    } catch (e) {
        console.error("[ERROR] 知识库上传过程出错:", e);
        alert('上传失败: ' + e.message);
    } finally {
        btn.innerHTML = originalHtml;
        btn.disabled = false;
        console.log("[DEBUG] 上传按钮状态已恢复");
    }
}

async function deleteKbFile(id) {
    if (!confirm('确定要删除该文档吗？')) return;
    try {
        await fetch(`/api/knowledge-base/${id}`, { 
            method: 'DELETE',
            headers: {'Authorization': `Bearer ${state.token}`}
        });
        loadKbFiles();
    } catch (e) {
        alert('删除失败');
    }
}

// --- 文本块浏览弹窗 ---

async function viewKbChunks(itemId, filename) {
    // 创建或获取弹窗
    let modal = document.getElementById('chunks-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'chunks-modal';
        modal.className = 'modal-overlay hidden';
        modal.innerHTML = `
            <div class="modal-content" style="max-width:800px; max-height:85vh; display:flex; flex-direction:column;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-shrink:0;">
                    <div class="modal-title" id="chunks-modal-title">文本块浏览</div>
                    <i class="fas fa-times" onclick="closeChunksModal()" style="cursor:pointer; font-size:18px; color:#999;"></i>
                </div>
                <div id="chunks-preview" style="flex-shrink:0;"></div>
                <div id="chunks-stats" style="color:#999; font-size:12px; margin-bottom:12px; flex-shrink:0;"></div>
                <div id="chunks-container" style="flex:1; overflow-y:auto; min-height:0;"></div>
            </div>
        `;
        document.body.appendChild(modal);
    }

    // 显示加载状态
    document.getElementById('chunks-modal-title').textContent = `📄 ${filename}`;
    document.getElementById('chunks-preview').innerHTML = '';
    document.getElementById('chunks-stats').textContent = '加载中...';
    document.getElementById('chunks-container').innerHTML = '<div style="text-align:center; padding:40px; color:#666;"><i class="fas fa-spinner fa-spin"></i> 正在加载文本块...</div>';
    modal.classList.remove('hidden');

    try {
        const res = await fetch(`/api/knowledge-base/${itemId}/chunks`, {
            headers: {'Authorization': `Bearer ${state.token}`}
        });
        if (!res.ok) throw new Error('加载失败');
        const data = await res.json();

        if (!data.chunks || data.chunks.length === 0) {
            document.getElementById('chunks-stats').textContent = '';
            document.getElementById('chunks-container').innerHTML = '<div style="text-align:center; padding:40px; color:#666;">暂无文本块数据</div>';
            return;
        }

        // 摘要不显示

        // 统计信息
        const totalTokens = data.chunks.reduce((sum, c) => sum + (c.n_tokens || 0), 0);
        document.getElementById('chunks-stats').textContent = `共 ${data.total} 个文本块，约 ${totalTokens.toLocaleString()} tokens`;

        // 渲染文本块列表
        document.getElementById('chunks-container').innerHTML = data.chunks.map((chunk, idx) => `
            <div style="background:#1f1f1f; border:1px solid #333; border-radius:8px; padding:14px; margin-bottom:10px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <span style="color:#4d6bfe; font-size:12px; font-weight:500;">文本块 #${idx + 1}</span>
                    <span style="color:#666; font-size:11px;">${chunk.n_tokens || 0} tokens</span>
                </div>
                <div style="color:#ddd; font-size:13px; line-height:1.7; white-space:pre-wrap; word-break:break-word;">${escapeHtml(chunk.text)}</div>
            </div>
        `).join('');

    } catch (e) {
        document.getElementById('chunks-stats').textContent = '';
        document.getElementById('chunks-container').innerHTML = `<div style="text-align:center; padding:40px; color:#cf6679;">加载失败: ${e.message}</div>`;
    }
}

function closeChunksModal() {
    const modal = document.getElementById('chunks-modal');
    if (modal) modal.classList.add('hidden');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// --- Utils ---

function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

function formatSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function getStatusBadge(status) {
    if (status === 'indexing' || status === 'pending') 
        return '<span class="status-tag indexing"><i class="fas fa-spinner fa-spin"></i> 正在建立索引</span>';
    if (status === 'success') 
        return '<span class="status-tag success"><i class="fas fa-check"></i> 已完成</span>';
    if (status === 'error') 
        return '<span class="status-tag error"><i class="fas fa-times"></i> 失败</span>';
    return status;
}

// ==================== 系统设置 ====================

function toggleSettings() {
    if (elements.settingsView.classList.contains('hidden')) {
        elements.chatView.classList.add('hidden');
        elements.kbView.classList.add('hidden');
        elements.wechatView.classList.add('hidden');
        if (elements.userListView) elements.userListView.classList.add('hidden');
        if (elements.agentConfigView) elements.agentConfigView.classList.add('hidden');
        elements.settingsView.classList.remove('hidden');
        state.currentView = 'settings';
        closeSidebar();
        stopKbPolling();
        loadSettings();
    }
}

// ==================== 智能体配置 ====================

function toggleAgentConfig() {
    if (!elements.agentConfigView) return;
    if (elements.agentConfigView.classList.contains('hidden')) {
        elements.chatView.classList.add('hidden');
        elements.kbView.classList.add('hidden');
        elements.wechatView.classList.add('hidden');
        elements.settingsView.classList.add('hidden');
        if (elements.userListView) elements.userListView.classList.add('hidden');
        elements.agentConfigView.classList.remove('hidden');
        state.currentView = 'agent-config';
        closeSidebar();
        stopKbPolling();
        loadAgentConfig();
    }
}

async function loadAgentConfig() {
    try {
        const res = await fetch('/api/agent-config', {
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
        if (!res.ok) throw new Error('加载失败');
        const data = await res.json();
        document.getElementById('agent-system-prompt').value = data.system_prompt || '';
        document.getElementById('agent-opening-message').value = data.opening_message || '';
        state.agentOpeningEnabled = data.opening_enabled !== false;
        updatePromptCount(document.getElementById('agent-system-prompt'));
        renderOpeningToggle();
    } catch (e) {
        console.error('加载智能体配置失败', e);
    }
}

async function saveAgentConfig() {
    const promptEl = document.getElementById('agent-system-prompt');
    const errorEl = document.getElementById('agent-prompt-error');
    const systemPrompt = promptEl.value.trim();

    if (!systemPrompt) {
        errorEl.style.display = 'inline';
        promptEl.style.borderColor = '#cf6679';
        return;
    }
    errorEl.style.display = 'none';
    promptEl.style.borderColor = '#444';

    const openingMessage = document.getElementById('agent-opening-message').value.trim();

    try {
        const res = await fetch('/api/agent-config', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${state.token}`
            },
            body: JSON.stringify({
                system_prompt: systemPrompt,
                opening_message: openingMessage,
                opening_enabled: state.agentOpeningEnabled
            })
        });
        if (!res.ok) throw new Error('保存失败');
        showToast('配置已保存');
        loadOpeningMessage();
    } catch (e) {
        showToast('保存失败：' + e.message, true);
    }
}

function updatePromptCount(el) {
    const count = el.value.length;
    const countEl = document.getElementById('agent-prompt-count');
    if (countEl) countEl.textContent = count + '/10000';
    if (countEl) countEl.style.color = count > 10000 ? '#cf6679' : '#666';
}

function toggleOpeningEnabled() {
    state.agentOpeningEnabled = !state.agentOpeningEnabled;
    renderOpeningToggle();
}

function renderOpeningToggle() {
    const toggle = document.getElementById('opening-toggle');
    const dot = document.getElementById('opening-toggle-dot');
    if (!toggle || !dot) return;
    if (state.agentOpeningEnabled) {
        toggle.style.background = '#4d6bfe';
        dot.style.left = '18px';
    } else {
        toggle.style.background = '#555';
        dot.style.left = '2px';
    }
}

async function generatePrompt() {
    const promptEl = document.getElementById('agent-system-prompt');
    const text = promptEl.value.trim();
    if (!text) { showToast('请先填写提示词内容', true); return; }

    const btn = document.querySelector('[onclick="generatePrompt()"]');
    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 生成中...';

    try {
        const res = await fetch('/api/agent-config/generate-prompt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
            body: JSON.stringify({ prompt: text })
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || '生成失败');
        }
        const data = await res.json();
        promptEl.value = data.optimized_prompt;
        updatePromptCount(promptEl);
        showToast('提示词已优化生成');
    } catch (e) {
        showToast('生成失败：' + e.message, true);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalHtml;
    }
}

async function generateOpening() {
    // 优先用提示词内容作为参考，其次用开场白现有内容
    const promptEl = document.getElementById('agent-system-prompt');
    const openingEl = document.getElementById('agent-opening-message');
    const refText = (promptEl.value.trim() || openingEl.value.trim());
    if (!refText) { showToast('请先填写提示词或开场白内容', true); return; }

    const btn = document.querySelector('[onclick="generateOpening()"]');
    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 生成中...';

    try {
        const res = await fetch('/api/agent-config/generate-opening', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${state.token}` },
            body: JSON.stringify({ prompt: refText })
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || '生成失败');
        }
        const data = await res.json();
        openingEl.value = data.optimized_opening;
        showToast('开场白已生成');
    } catch (e) {
        showToast('生成失败：' + e.message, true);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalHtml;
    }
}

async function loadOpeningMessage() {
    try {
        const res = await fetch('/api/agent-config/public', {
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
        if (!res.ok) return;
        const data = await res.json();
        const welcomeTitle = document.querySelector('.welcome-title');
        if (welcomeTitle) {
            if (data.enabled && data.opening_message) {
                welcomeTitle.innerHTML = data.opening_message;
            } else {
                welcomeTitle.innerHTML = '<span style="color:#4d6bfe">🐋</span>今天有什么可以帮您？';
            }
        }
    } catch (e) {
        // 加载失败时保持默认欢迎语
    }
}

function showToast(msg, isError = false) {
    let toast = document.getElementById('_kiro_toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = '_kiro_toast';
        toast.style.cssText = 'position:fixed;bottom:30px;left:50%;transform:translateX(-50%);padding:10px 20px;border-radius:8px;font-size:13px;color:#fff;z-index:9999;transition:opacity 0.3s;pointer-events:none;';
        document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.style.background = isError ? '#cf6679' : '#4d6bfe';
    toast.style.opacity = '1';
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => { toast.style.opacity = '0'; }, 2500);
}

async function loadSettings() {
    elements.settingsContainer.innerHTML = '<div style="text-align:center; color:#666; padding:40px;">加载中...</div>';
    try {
        const res = await fetch('/api/settings', {
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
        if (!res.ok) throw new Error('加载失败');
        const data = await res.json();
        renderSettings(data.groups, data.is_admin);
    } catch (e) {
        elements.settingsContainer.innerHTML = '<div style="text-align:center; color:#cf6679; padding:40px;">加载设置失败: ' + e.message + '</div>';
    }
}

function renderSettings(groups, isAdmin) {
    let html = '';

    // 普通用户显示说明提示
    if (!isAdmin) {
        html += `<div style="background:#1a2a1a; border:1px solid #2d5a2d; border-radius:8px; padding:14px 16px; margin-bottom:20px; color:#7ec87e; font-size:13px; line-height:1.6;">
            <div style="font-weight:600; margin-bottom:6px;">⚙️ 个人 AI 配置</div>
            <div>请填写您自己的 API Key，系统将使用您的配置进行对话。未配置时无法使用 AI 功能。</div>
            <div style="margin-top:6px; color:#999;">· DeepSeek API Key：用于文字对话和推理</div>
            <div style="color:#999;">· Gemini API Key：用于图片识别功能</div>
            <div style="color:#999;">· SerpAPI Key：用于联网搜索功能</div>
            <div style="color:#999;">· API 密钥：您的专属密钥，可用于对外 API 调用身份验证</div>
            <div style="color:#999;">· MinerU API Token：用于上传知识库时高精度文档解析（支持 PDF/DOCX/PPT/图片 OCR）</div>
        </div>`;
    }

    for (const [groupKey, group] of Object.entries(groups)) {
        html += `<div style="margin-bottom: 28px;">`;
        html += `<div style="font-size: 15px; font-weight: 600; color: #4d6bfe; margin-bottom: 14px; padding-bottom: 8px; border-bottom: 1px solid #333;">${group.label}</div>`;
        html += `<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px 20px;">`;
        for (const item of group.items) {
            const inputId = `setting-${item.key}`;
            let inputHtml = '';
            if (item.type === 'select' && item.options && item.options.length) {
                inputHtml = `<select id="${inputId}" data-key="${item.key}" style="width:100%; padding:8px 10px; background:#2d2d2d; border:1px solid #444; color:white; border-radius:6px;">
                    ${item.options.map(opt => `<option value="${opt}" ${item.value === opt ? 'selected' : ''}>${opt}</option>`).join('')}
                </select>`;
            } else if (item.type === 'bool') {
                const checked = item.value === 'True' || item.value === 'true' || item.value === '1';
                inputHtml = `<select id="${inputId}" data-key="${item.key}" style="width:100%; padding:8px 10px; background:#2d2d2d; border:1px solid #444; color:white; border-radius:6px;">
                    <option value="true" ${checked ? 'selected' : ''}>启用 (true)</option>
                    <option value="false" ${!checked ? 'selected' : ''}>禁用 (false)</option>
                </select>`;
            } else if (item.type === 'readonly') {
                inputHtml = `<div style="display:flex;gap:6px;align-items:center;">
                    <input type="text" id="${inputId}" data-key="${item.key}" value="${escapeHtml(item.value)}" readonly
                        style="flex:1; padding:8px 10px; background:#1a1a2e; border:1px solid #4d6bfe55; color:#7ec8ff; border-radius:6px; font-family:monospace; font-size:13px; cursor:text;"
                        onclick="this.select()">
                    <button type="button" onclick="copyToClipboard('${escapeHtml(item.value)}','API 密钥')"
                        style="padding:8px 12px; background:#4d6bfe; border:none; color:white; border-radius:6px; cursor:pointer; font-size:12px; white-space:nowrap;">复制</button>
                </div>`;
            } else if (item.type === 'password') {
                inputHtml = `<div style="display:flex; gap:8px; align-items:center;">
                    <input type="text" id="${inputId}" data-key="${item.key}" value="${escapeHtml(item.value)}"
                        style="flex:1; padding:8px 10px; background:#2d2d2d; border:1px solid #444; color:white; border-radius:6px; font-family:monospace;"
                        placeholder="${isAdmin ? '输入新值以更新' : '请输入您的 ' + item.label}">
                    <button type="button" onclick="copyToClipboard(document.getElementById('${inputId}').value, '${item.label}')"
                        style="padding:8px 12px; background:#4d6bfe; border:none; color:white; border-radius:6px; cursor:pointer; font-size:12px; white-space:nowrap;">
                        <i class='fas fa-copy'></i> 复制</button>
                </div>`;
            } else {
                inputHtml = `<input type="text" id="${inputId}" data-key="${item.key}" value="${escapeHtml(item.value)}" 
                    style="width:100%; padding:8px 10px; background:#2d2d2d; border:1px solid #444; color:white; border-radius:6px;"
                    placeholder="${isAdmin ? '' : '请输入 ' + item.label}">`;
            }
            html += `<div>
                <label for="${inputId}" style="display:block; font-size:12px; color:#999; margin-bottom:4px;">${item.label}</label>
                ${inputHtml}
            </div>`;
        }
        html += `</div>`;

        // 普通用户：各分组底部显示申请 Key 的彩色按钮
        if (!isAdmin) {
            const applyBtnMap = {
                deepseek: {
                    text: '🚀 申请 DeepSeek API Key',
                    url: 'https://platform.deepseek.com/sign_in',
                    gradient: 'linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f64f59 100%)'
                },
                gemini: {
                    text: '✨ 申请 Gemini API Key',
                    url: 'https://api.kuai.host/register?aff=5dQ8',
                    gradient: 'linear-gradient(135deg, #11998e 0%, #38ef7d 50%, #4d6bfe 100%)'
                },
                search: {
                    text: '🔍 申请 SerpAPI Key',
                    url: 'https://serpapi.com/dashboard',
                    gradient: 'linear-gradient(135deg, #f7971e 0%, #ffd200 50%, #f64f59 100%)'
                },
                mineru: {
                    text: '📄 申请 MinerU API Token',
                    url: 'https://mineru.net/apiManage/token',
                    gradient: 'linear-gradient(135deg, #667eea 0%, #f64f59 30%, #ffd200 60%, #38ef7d 100%)',
                    animate: true
                },
                embedding: {
                    text: '🔑 申请阿里百炼 Embedding API Key',
                    url: 'https://bailian.console.aliyun.com/cn-beijing/?spm=a2c4g.11186623.0.0.75784c35CXbDm4&tab=model#/api-key',
                    gradient: 'linear-gradient(135deg, #667eea 0%, #f64f59 30%, #ffd200 60%, #38ef7d 100%)',
                    animate: true
                }
            };
            if (applyBtnMap[groupKey]) {
                const btn = applyBtnMap[groupKey];
                const animStyle = btn.animate
                    ? `background-size:200% 200%; animation:rainbowShift 3s ease infinite;`
                    : '';
                html += `<div style="margin-top:14px;">
                    <a href="${btn.url}" target="_blank" rel="noopener noreferrer"
                        style="display:inline-block; padding:10px 22px; border-radius:8px;
                               background:${btn.gradient}; color:white; font-size:13px; font-weight:600;
                               text-decoration:none; letter-spacing:0.5px;
                               box-shadow:0 4px 15px rgba(0,0,0,0.3);
                               transition:opacity .2s, transform .2s; ${animStyle}"
                        onmouseover="this.style.opacity='.85';this.style.transform='translateY(-1px)'"
                        onmouseout="this.style.opacity='1';this.style.transform='translateY(0)'"
                    >${btn.text}</a>
                </div>`;
            }
        }

        html += `</div>`;
    }
    elements.settingsContainer.innerHTML = html;
}

async function saveSettings() {
    const inputs = elements.settingsContainer.querySelectorAll('[data-key]');
    const payload = {};
    inputs.forEach(el => {
        const key = el.dataset.key;
        // 跳过只读字段（如 USER_API_KEY）
        if (el.readOnly) return;
        const val = el.tagName === 'SELECT' ? el.value : el.value;
        // 跳过未修改的密码字段（值仍以 ****** 结尾说明没改过）
        if (val.endsWith('******')) return;
        payload[key] = val;
    });

    try {
        const res = await fetch('/api/settings', {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${state.token}`
            },
            body: JSON.stringify({ settings: payload })
        });
        if (!res.ok) throw new Error('保存失败');
        const data = await res.json();
        alert(`保存成功！${data.message}`);
        // 重新加载以显示最新值
        loadSettings();
    } catch (e) {
        alert('保存失败: ' + e.message);
    }
}


// --- Wechat Config Management ---

function toggleWechatConfig() {
    if (elements.wechatView.classList.contains('hidden')) {
        elements.chatView.classList.add('hidden');
        elements.kbView.classList.add('hidden');
        elements.settingsView.classList.add('hidden');
        if (elements.userListView) elements.userListView.classList.add('hidden');
        if (elements.agentConfigView) elements.agentConfigView.classList.add('hidden');
        elements.wechatView.classList.remove('hidden');
        state.currentView = 'wechat';
        closeSidebar();
        loadWechatConfigs();
    }
}

async function loadWechatConfigs() {
    elements.wechatConfigList.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#666;">加载中...</td></tr>';
    
    try {
        const res = await fetch('/api/wechat/configs', {
            headers: {'Authorization': `Bearer ${state.token}`}
        });
        if (!res.ok) throw new Error("加载失败");
        state.wechatConfigs = await res.json();
        renderWechatConfigTable(state.wechatConfigs);
        // 同步更新菜单tab的配置下拉
        populateMenuConfigSelect();
    } catch (e) {
        elements.wechatConfigList.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#cf6679;">加载失败</td></tr>';
    }
}

function renderWechatConfigTable(configs) {
    if (configs.length === 0) {
        elements.wechatConfigList.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#666;">暂无配置，请点击右上角新建。</td></tr>';
        return;
    }
    
    elements.wechatConfigList.innerHTML = configs.map(config => {
        const statusBadge = config.is_active 
            ? '<span class="status-tag success"><i class="fas fa-check"></i> 已启用</span>'
            : '<span class="status-tag" style="background:#444;"><i class="fas fa-pause"></i> 已停用</span>';
        
        const kbName = config.knowledge_base_id || '无';
        
        // 生成完整的服务器URL
        const fullServerUrl = window.location.origin + (config.server_url || '');
        
        return `
        <tr>
            <td>${escapeHtml(config.name)}</td>
            <td><code style="font-size:11px; color:#4d6bfe;">${escapeHtml(config.appid)}</code></td>
            <td>${escapeHtml(kbName)}</td>
            <td>${statusBadge}</td>
            <td>${new Date(config.created_at).toLocaleString('zh-CN')}</td>
            <td>
                <button onclick="viewWechatConfig(${config.id})" style="background:none; border:none; color:#4d6bfe; cursor:pointer; margin-right:8px;" title="查看详情">
                    <i class="fas fa-eye"></i>
                </button>
                <button onclick="editWechatConfig(${config.id})" style="background:none; border:none; color:#4d6bfe; cursor:pointer; margin-right:8px;" title="编辑">
                    <i class="fas fa-edit"></i>
                </button>
                <button onclick="deleteWechatConfig(${config.id})" style="background:none; border:none; color:#cf6679; cursor:pointer;" title="删除">
                    <i class="fas fa-trash"></i>
                </button>
            </td>
        </tr>`;
    }).join('');
}

function openWechatConfigModal(configId = null) {
    state.currentWechatConfig = configId;
    
    if (configId) {
        // 编辑模式
        document.getElementById('wechat-modal-title').textContent = '编辑微信配置';
        const config = state.wechatConfigs.find(c => c.id === configId);
        if (config) {
            document.getElementById('wechat-name').value = config.name;
            document.getElementById('wechat-appid').value = config.appid;
            document.getElementById('wechat-token').value = config.token;
            document.getElementById('wechat-aes-key').value = config.encoding_aes_key;
            document.getElementById('wechat-kb-id').value = config.knowledge_base_id || '';
            document.getElementById('wechat-welcome').value = config.welcome_message || '';
            document.getElementById('wechat-default-reply').value = config.default_reply || '';
            document.getElementById('wechat-enable-ai').checked = config.enable_ai_reply;
            document.getElementById('wechat-is-active').checked = config.is_active;
            
            // 显示服务器URL
            const serverUrl = window.location.origin + (config.server_url || '');
            document.getElementById('wechat-server-url-display').value = serverUrl;
            document.getElementById('wechat-server-url-group').style.display = 'block';
        }
    } else {
        // 新建模式
        document.getElementById('wechat-modal-title').textContent = '新建微信配置';
        document.getElementById('wechat-config-form').reset();
        document.getElementById('wechat-enable-ai').checked = true;
        document.getElementById('wechat-is-active').checked = true;
        document.getElementById('wechat-server-url-group').style.display = 'none';
    }
    
    elements.wechatConfigModal.classList.remove('hidden');
}

function closeWechatConfigModal() {
    elements.wechatConfigModal.classList.add('hidden');
    state.currentWechatConfig = null;
}

async function saveWechatConfig(e) {
    e.preventDefault();
    
    const data = {
        name: document.getElementById('wechat-name').value.trim(),
        appid: document.getElementById('wechat-appid').value.trim(),
        token: document.getElementById('wechat-token').value.trim(),
        encoding_aes_key: document.getElementById('wechat-aes-key').value.trim(),
        knowledge_base_id: document.getElementById('wechat-kb-id').value.trim() || null,
        welcome_message: document.getElementById('wechat-welcome').value.trim() || null,
        default_reply: document.getElementById('wechat-default-reply').value.trim() || null,
        enable_ai_reply: document.getElementById('wechat-enable-ai').checked,
        is_active: document.getElementById('wechat-is-active').checked
    };
    
    const saveBtn = document.getElementById('wechat-save-btn');
    const originalText = saveBtn.textContent;
    saveBtn.textContent = '保存中...';
    saveBtn.disabled = true;
    
    try {
        let res;
        if (state.currentWechatConfig) {
            // 更新
            res = await fetch(`/api/wechat/configs/${state.currentWechatConfig}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${state.token}`
                },
                body: JSON.stringify(data)
            });
        } else {
            // 新建
            res = await fetch('/api/wechat/configs', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${state.token}`
                },
                body: JSON.stringify(data)
            });
        }
        
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || '保存失败');
        }
        
        alert('保存成功！');
        closeWechatConfigModal();
        loadWechatConfigs();
    } catch (e) {
        alert('保存失败: ' + e.message);
    } finally {
        saveBtn.textContent = originalText;
        saveBtn.disabled = false;
    }
}

async function viewWechatConfig(configId) {
    const config = state.wechatConfigs.find(c => c.id === configId);
    if (!config) return;
    
    const serverUrl = window.location.origin + (config.server_url || '');
    
    // 创建自定义模态框
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.style.display = 'flex';
    modal.innerHTML = `
        <div class="modal-content" style="max-width: 600px; max-height: 90vh; overflow-y: auto;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                <div class="modal-title">微信配置详情</div>
                <i class="fas fa-times" onclick="this.closest('.modal-overlay').remove()" style="cursor: pointer; font-size: 18px; color: #999;"></i>
            </div>
            
            <div style="background: #1f1f1f; border: 1px solid #333; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                <div style="color: #4d6bfe; font-size: 14px; margin-bottom: 12px; font-weight: 500;">
                    <i class="fas fa-cog"></i> 基本信息
                </div>
                <div style="font-size: 13px; line-height: 2; color: #ccc;">
                    <div><span style="color: #999;">配置名称：</span>${escapeHtml(config.name)}</div>
                    <div><span style="color: #999;">AppID：</span><code style="color: #4d6bfe;">${escapeHtml(config.appid)}</code></div>
                    <div><span style="color: #999;">Token：</span><code style="color: #4d6bfe;">${escapeHtml(config.token)}</code></div>
                    <div><span style="color: #999;">EncodingAESKey：</span><code style="color: #4d6bfe; font-size: 11px;">${escapeHtml(config.encoding_aes_key)}</code></div>
                </div>
            </div>
            
            <div style="background: #1f1f1f; border: 1px solid #333; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                <div style="color: #4d6bfe; font-size: 14px; margin-bottom: 12px; font-weight: 500;">
                    <i class="fas fa-server"></i> 服务器配置
                </div>
                <div style="font-size: 13px; color: #ccc; margin-bottom: 10px;">
                    <span style="color: #999;">URL服务器地址：</span>
                </div>
                <div style="display: flex; gap: 8px; align-items: center; padding: 10px; background: #2d2d2d; border: 1px solid #444; border-radius: 6px;">
                    <input type="text" value="${serverUrl}" readonly
                           style="flex: 1; background: transparent; border: none; color: #4d6bfe; font-size: 12px; outline: none;">
                    <button onclick="copyToClipboard('${serverUrl}', '服务器URL')" class="footer-btn" style="border: 1px solid #4d6bfe; color: #4d6bfe; white-space: nowrap; padding: 6px 12px;">
                        <i class="fas fa-copy"></i> 复制
                    </button>
                </div>
            </div>
            
            <div style="background: #1f1f1f; border: 1px solid #333; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                <div style="color: #4d6bfe; font-size: 14px; margin-bottom: 12px; font-weight: 500;">
                    <i class="fas fa-robot"></i> AI配置
                </div>
                <div style="font-size: 13px; line-height: 2; color: #ccc;">
                    <div><span style="color: #999;">关联知识库：</span>${config.knowledge_base_id ? '<code style="color: #4d6bfe;">' + escapeHtml(config.knowledge_base_id) + '</code>' : '<span style="color: #666;">未配置</span>'}</div>
                    <div><span style="color: #999;">欢迎消息：</span>${config.welcome_message ? escapeHtml(config.welcome_message) : '<span style="color: #666;">未配置</span>'}</div>
                    <div><span style="color: #999;">默认回复：</span>${config.default_reply ? escapeHtml(config.default_reply) : '<span style="color: #666;">未配置</span>'}</div>
                    <div><span style="color: #999;">公众号/服务号接入：</span>${config.enable_ai_reply ? '<span style="color: #4d6bfe;">已启用</span>' : '<span style="color: #666;">已停用</span>'}</div>
                    <div><span style="color: #999;">配置状态：</span>${config.is_active ? '<span style="color: #4d6bfe;">已启用</span>' : '<span style="color: #666;">已停用</span>'}</div>
                </div>
            </div>
            
            <div style="background: #1f1f1f; border: 1px solid #333; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                <div style="color: #4d6bfe; font-size: 14px; margin-bottom: 12px; font-weight: 500;">
                    <i class="fas fa-info-circle"></i> 配置说明
                </div>
                <div style="font-size: 12px; line-height: 1.8; color: #999;">
                    <div style="margin-bottom: 8px;">请在微信公众平台进行以下配置：</div>
                    <ol style="margin: 0; padding-left: 20px;">
                        <li>登录 <a href="https://mp.weixin.qq.com/" target="_blank" style="color: #4d6bfe;">微信公众平台</a></li>
                        <li>进入"开发" → "基本配置" → "服务器配置"</li>
                        <li>填写以下信息：
                            <ul style="list-style: none; padding-left: 0; margin-top: 6px;">
                                <li>• URL：<code style="color: #4d6bfe; font-size: 11px;">${serverUrl}</code></li>
                                <li>• Token：<code style="color: #4d6bfe;">${escapeHtml(config.token)}</code></li>
                                <li>• EncodingAESKey：<code style="color: #4d6bfe; font-size: 10px;">${escapeHtml(config.encoding_aes_key)}</code></li>
                                <li>• 消息加解密方式：<strong style="color: #4d6bfe;">安全模式（推荐）</strong></li>
                            </ul>
                        </li>
                        <li>点击"提交"完成验证</li>
                        <li>启用服务器配置</li>
                    </ol>
                </div>
            </div>
            
            <div style="font-size: 11px; color: #666; text-align: center;">
                创建时间：${new Date(config.created_at).toLocaleString('zh-CN')} | 
                更新时间：${new Date(config.updated_at).toLocaleString('zh-CN')}
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
}

function copyToClipboard(text, label) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            showToast(`${label}已复制到剪贴板`, 'success');
        }).catch(err => {
            fallbackCopyText(text, label);
        });
    } else {
        fallbackCopyText(text, label);
    }
}

function fallbackCopyText(text, label) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    
    textarea.select();
    try {
        document.execCommand('copy');
        showToast(`${label}已复制到剪贴板`, 'success');
    } catch (err) {
        showToast('复制失败，请手动复制', 'error');
    }
    
    document.body.removeChild(textarea);
}

async function editWechatConfig(configId) {
    openWechatConfigModal(configId);
}

async function deleteWechatConfig(configId) {
    if (!confirm('确定要删除这个配置吗？删除后无法恢复。')) return;
    
    try {
        const res = await fetch(`/api/wechat/configs/${configId}`, {
            method: 'DELETE',
            headers: {'Authorization': `Bearer ${state.token}`}
        });
        
        if (!res.ok) throw new Error('删除失败');
        
        alert('删除成功！');
        loadWechatConfigs();
    } catch (e) {
        alert('删除失败: ' + e.message);
    }
}


// --- API Documentation ---

function openApiDocs() {
    // 在新标签页打开API文档
    window.open('/docs#/', '_blank');
    
    // 移动端关闭侧边栏
    closeSidebar();
}


// --- Token and AESKey Generation ---

function generateToken() {
    // 生成3-32位的随机Token（字母和数字）
    const length = 32; // 使用最大长度
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let token = '';
    
    for (let i = 0; i < length; i++) {
        token += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    
    document.getElementById('wechat-token').value = token;
    
    // 显示提示
    showToast('Token已生成', 'success');
}

function generateAESKey() {
    // 根据微信官方文档生成43位EncodingAESKey
    // EncodingAESKey是Base64编码，但微信平台可能对某些字符有限制
    // 为了兼容性，我们只使用字母和数字（不使用+和/）
    
    // 生成32字节随机数据
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    
    // 转换为Base64，但替换特殊字符
    let binary = '';
    bytes.forEach(byte => binary += String.fromCharCode(byte));
    let base64 = btoa(binary);
    
    // 替换Base64中的特殊字符为字母数字
    // + 替换为随机字母, / 替换为随机数字, = 移除
    base64 = base64.replace(/\+/g, () => {
        const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
        return letters.charAt(Math.floor(Math.random() * letters.length));
    });
    base64 = base64.replace(/\//g, () => {
        const digits = '0123456789';
        return digits.charAt(Math.floor(Math.random() * digits.length));
    });
    base64 = base64.replace(/=/g, '');
    
    // 确保正好43位
    if (base64.length > 43) {
        base64 = base64.substring(0, 43);
    } else if (base64.length < 43) {
        // 补充随机字符到43位
        const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
        while (base64.length < 43) {
            base64 += chars.charAt(Math.floor(Math.random() * chars.length));
        }
    }
    
    document.getElementById('wechat-aes-key').value = base64;
    
    // 显示提示
    showToast('EncodingAESKey已生成（43位字母数字）', 'success');
}

function copyServerUrl() {
    const urlInput = document.getElementById('wechat-server-url-display');
    const url = urlInput.value;
    
    // 复制到剪贴板
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(() => {
            showToast('服务器URL已复制到剪贴板', 'success');
        }).catch(err => {
            // 降级方案
            fallbackCopyText(url);
        });
    } else {
        // 降级方案
        fallbackCopyText(url);
    }
}

function fallbackCopyText(text) {
    // 创建临时textarea
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    
    // 选择并复制
    textarea.select();
    try {
        document.execCommand('copy');
        showToast('服务器URL已复制到剪贴板', 'success');
    } catch (err) {
        showToast('复制失败，请手动复制', 'error');
    }
    
    document.body.removeChild(textarea);
}

function showToast(message, type = 'info') {
    // 创建toast元素
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        background: ${type === 'success' ? '#4d6bfe' : type === 'error' ? '#cf6679' : '#666'};
        color: white;
        border-radius: 6px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        z-index: 10000;
        font-size: 14px;
        animation: slideIn 0.3s ease;
    `;
    
    const icon = type === 'success' ? '✓' : type === 'error' ? '✗' : 'ℹ';
    toast.innerHTML = `<i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'times-circle' : 'info-circle'}"></i> ${message}`;
    
    document.body.appendChild(toast);
    
    // 3秒后自动移除
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => {
            document.body.removeChild(toast);
        }, 300);
    }, 3000);
}

// 添加动画样式
if (!document.getElementById('toast-animations')) {
    const style = document.createElement('style');
    style.id = 'toast-animations';
    style.textContent = `
        @keyframes slideIn {
            from {
                transform: translateX(400px);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
        @keyframes slideOut {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(400px);
                opacity: 0;
            }
        }
    `;
    document.head.appendChild(style);
}

// ==================== 用户列表（管理员）====================

let resetPwdTargetId = null;

function toggleUserList() {
    elements.chatView.classList.add('hidden');
    elements.kbView.classList.add('hidden');
    elements.wechatView.classList.add('hidden');
    elements.settingsView.classList.add('hidden');
    if (elements.agentConfigView) elements.agentConfigView.classList.add('hidden');
    if (elements.userListView) elements.userListView.classList.remove('hidden');
    state.currentView = 'userList';
    closeSidebar();
    loadUserList();
}

async function loadUserList() {
    const tbody = document.getElementById('user-list-tbody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#666;padding:20px;">加载中...</td></tr>';
    try {
        const res = await fetch('/api/admin/users', {
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
        if (!res.ok) throw new Error('加载失败');
        const users = await res.json();
        if (!users.length) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#666;padding:20px;">暂无用户</td></tr>';
            return;
        }
        tbody.innerHTML = users.map(u => `
            <tr>
                <td>${u.id}</td>
                <td>${escapeHtml(u.username)}</td>
                <td>${escapeHtml(u.email)}</td>
                <td><span style="color:${u.role==='admin'?'#4d6bfe':'#aaa'}">${u.role}</span></td>
                <td><span style="color:${u.status==='active'?'#4caf50':'#cf6679'}">${u.status}</span></td>
                <td style="font-size:12px;color:#888;">${u.created_at ? u.created_at.slice(0,10) : '-'}</td>
                <td style="font-size:12px;color:#888;">${u.last_login ? u.last_login.slice(0,10) : '从未'}</td>
                <td>
                    <div style="display:flex;gap:8px;">
                        <button onclick="openResetPwdModal(${u.id},'${escapeHtml(u.username)}')"
                            style="padding:5px 10px;background:#4d6bfe;border:none;color:white;border-radius:5px;cursor:pointer;font-size:12px;">
                            <i class="fas fa-key"></i> 重置密码
                        </button>
                        ${u.role !== 'admin' ? `<button onclick="deleteUser(${u.id},'${escapeHtml(u.username)}')"
                            style="padding:5px 10px;background:#cf6679;border:none;color:white;border-radius:5px;cursor:pointer;font-size:12px;">
                            <i class="fas fa-trash"></i> 删除
                        </button>` : ''}
                    </div>
                </td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:#cf6679;padding:20px;">${e.message}</td></tr>`;
    }
}

async function deleteUser(userId, username) {
    if (!confirm(`确定要删除用户「${username}」及其所有数据（对话、知识库等）吗？此操作不可恢复！`)) return;
    try {
        const res = await fetch(`/api/admin/users/${userId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '删除失败');
        showToast(data.message, 'success');
        loadUserList();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

function openResetPwdModal(userId, username) {
    resetPwdTargetId = userId;
    document.getElementById('reset-pwd-username').textContent = `用户：${username}`;
    document.getElementById('reset-pwd-input').value = '';
    document.getElementById('reset-pwd-modal').classList.remove('hidden');
    document.getElementById('reset-pwd-modal').style.display = 'flex';
}

function closeResetPwdModal() {
    resetPwdTargetId = null;
    document.getElementById('reset-pwd-modal').classList.add('hidden');
    document.getElementById('reset-pwd-modal').style.display = 'none';
}

async function confirmResetPassword() {
    const pwd = document.getElementById('reset-pwd-input').value.trim();
    if (!pwd) { showToast('请输入新密码', 'error'); return; }
    try {
        const res = await fetch(`/api/admin/users/${resetPwdTargetId}/password`, {
            method: 'PUT',
            headers: { 'Authorization': `Bearer ${state.token}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_password: pwd })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '重置失败');
        showToast(data.message, 'success');
        closeResetPwdModal();
    } catch (e) {
        showToast(e.message, 'error');
    }
}


// ==================== 自定义菜单 ====================

// 菜单状态
const menuState = {
    configId: null,          // 当前选中的公众号配置ID
    draft: { button: [] },   // 草稿数据（最多3个一级菜单）
    selected: null,          // { parentIdx, subIdx } 当前选中的菜单项，subIdx=-1表示一级
    replyType: null,         // 当前回复弹窗类型
};

function switchWechatTab(tab) {
    const tabs = ['config', 'menu'];
    tabs.forEach(t => {
        document.getElementById(`wechat-tab-${t}`).style.borderBottomColor = t === tab ? '#4d6bfe' : 'transparent';
        document.getElementById(`wechat-tab-${t}`).style.color = t === tab ? '#4d6bfe' : '#999';
        document.getElementById(`wechat-panel-${t}`).style.display = t === tab ? '' : 'none';
    });
    if (tab === 'menu') {
        populateMenuConfigSelect();
    }
}

function populateMenuConfigSelect() {
    const sel = document.getElementById('menu-config-select');
    const prev = sel.value;
    sel.innerHTML = '<option value="">-- 选择公众号配置 --</option>';
    (state.wechatConfigs || []).forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.id;
        opt.textContent = `${c.name} (${c.appid})`;
        sel.appendChild(opt);
    });
    if (prev) sel.value = prev;
}

async function onMenuConfigChange() {
    const sel = document.getElementById('menu-config-select');
    const configId = parseInt(sel.value);
    menuState.configId = configId || null;

    const noTip = document.getElementById('menu-no-config-tip');
    const editorBody = document.getElementById('menu-editor-body');
    const appsecretPanel = document.getElementById('menu-appsecret-panel');
    const publishBtn = document.getElementById('menu-publish-btn');
    const draftBtn = document.getElementById('menu-draft-btn');
    const deleteBtn = document.getElementById('menu-delete-btn');

    if (!configId) {
        noTip.style.display = '';
        editorBody.style.display = 'none';
        appsecretPanel.style.display = 'none';
        publishBtn.style.display = 'none';
        draftBtn.style.display = 'none';
        deleteBtn.style.display = 'none';
        return;
    }

    noTip.style.display = 'none';
    publishBtn.style.display = '';
    draftBtn.style.display = '';
    deleteBtn.style.display = '';

    // 检查是否有appsecret
    const config = state.wechatConfigs.find(c => c.id === configId);
    if (!config.has_appsecret) {
        appsecretPanel.style.display = '';
        editorBody.style.display = 'none';
    } else {
        appsecretPanel.style.display = 'none';
        editorBody.style.display = 'flex';
        await loadMenuFromServer();
    }
}

async function saveAppsecret() {
    const val = document.getElementById('menu-appsecret-input').value.trim();
    if (!val) { showToast('请输入 AppSecret', 'error'); return; }
    try {
        const res = await fetch(`/api/wechat/configs/${menuState.configId}/appsecret`, {
            method: 'PUT',
            headers: { 'Authorization': `Bearer ${state.token}`, 'Content-Type': 'application/json' },
            body: JSON.stringify({ appsecret: val })
        });
        if (!res.ok) throw new Error('保存失败');
        showToast('AppSecret 已保存', 'success');
        // 更新本地state
        const cfg = state.wechatConfigs.find(c => c.id === menuState.configId);
        if (cfg) cfg.has_appsecret = true;
        document.getElementById('menu-appsecret-panel').style.display = 'none';
        document.getElementById('menu-editor-body').style.display = 'flex';
        await loadMenuFromServer();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function loadMenuFromServer() {
    try {
        const res = await fetch(`/api/wechat/configs/${menuState.configId}/menu`, {
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const data = await res.json();
        if (data.menu && data.menu.button) {
            menuState.draft = { button: data.menu.button };
        } else {
            menuState.draft = { button: [] };
        }
    } catch (e) {
        menuState.draft = { button: [] };
    }
    menuState.selected = null;
    renderPhoneMenu();
    showMenuForm(null);
}

// ---- 渲染手机菜单预览 ----
function renderPhoneMenu() {
    const bar = document.getElementById('phone-menu-bar');
    const subArea = document.getElementById('phone-submenu-area');
    const btns = menuState.draft.button || [];

    bar.innerHTML = btns.map((btn, i) => {
        const isSelected = menuState.selected && menuState.selected.parentIdx === i && menuState.selected.subIdx === -1;
        return `<div onclick="selectMenuItem(${i}, -1)" style="flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:8px 4px; cursor:pointer; border-right:1px solid #ddd; font-size:11px; color:${isSelected ? '#07c160' : '#333'}; background:${isSelected ? '#f0fff4' : 'transparent'}; border-bottom:${isSelected ? '2px solid #07c160' : '2px solid transparent'}; min-height:44px; position:relative;">
            <span style="word-break:break-all; text-align:center; line-height:1.3;">${escapeHtml(btn.name || '菜单')}</span>
            <i class="fas fa-trash" onclick="event.stopPropagation(); deleteMenuItem(${i}, -1)" style="position:absolute; top:2px; right:2px; font-size:9px; color:#cf6679; opacity:0.6;"></i>
        </div>`;
    }).join('');

    // 添加按钮（最多3个）
    if (btns.length < 3) {
        bar.innerHTML += `<div onclick="addTopMenuItem()" style="flex:1; display:flex; align-items:center; justify-content:center; cursor:pointer; color:#999; font-size:18px; min-height:44px; border-right:1px solid #ddd;">+</div>`;
    }

    // 渲染子菜单区域
    const sel = menuState.selected;
    if (sel && sel.parentIdx >= 0 && sel.subIdx === -1 && btns[sel.parentIdx]) {
        const parent = btns[sel.parentIdx];
        const subs = parent.sub_button || [];
        subArea.style.display = '';
        subArea.innerHTML = subs.map((sub, j) => {
            const isSubSel = sel.subIdx === j;
            return `<div onclick="selectMenuItem(${sel.parentIdx}, ${j})" style="display:flex; justify-content:space-between; align-items:center; padding:10px 14px; background:${isSubSel ? '#e8f5e9' : 'white'}; border-bottom:1px solid #eee; cursor:pointer; font-size:12px; color:#333;">
                <span>${escapeHtml(sub.name || '子菜单')}</span>
                <i class="fas fa-trash" onclick="event.stopPropagation(); deleteMenuItem(${sel.parentIdx}, ${j})" style="color:#cf6679; font-size:11px;"></i>
            </div>`;
        }).join('');
        if (subs.length < 5) {
            subArea.innerHTML += `<div onclick="addSubMenuItem(${sel.parentIdx})" style="padding:10px 14px; color:#07c160; font-size:12px; cursor:pointer; background:white; text-align:center;">+ 添加</div>`;
        }
    } else {
        subArea.style.display = 'none';
    }
}

function addTopMenuItem() {
    if ((menuState.draft.button || []).length >= 3) return;
    menuState.draft.button.push({ name: '新菜单', sub_button: [] });
    menuState.selected = { parentIdx: menuState.draft.button.length - 1, subIdx: -1 };
    renderPhoneMenu();
    showMenuForm(menuState.selected);
}

function addSubMenuItem(parentIdx) {
    const parent = menuState.draft.button[parentIdx];
    if (!parent.sub_button) parent.sub_button = [];
    if (parent.sub_button.length >= 5) return;
    // 一级菜单有子菜单时，一级菜单本身不能有type
    delete parent.type;
    delete parent.key;
    delete parent.url;
    parent.sub_button.push({ name: '新子菜单', type: 'click', key: `MENU_${Date.now()}` });
    const subIdx = parent.sub_button.length - 1;
    menuState.selected = { parentIdx, subIdx };
    renderPhoneMenu();
    showMenuForm(menuState.selected);
}

function deleteMenuItem(parentIdx, subIdx) {
    if (subIdx === -1) {
        menuState.draft.button.splice(parentIdx, 1);
        menuState.selected = null;
    } else {
        menuState.draft.button[parentIdx].sub_button.splice(subIdx, 1);
        menuState.selected = { parentIdx, subIdx: -1 };
    }
    renderPhoneMenu();
    showMenuForm(menuState.selected);
}

function selectMenuItem(parentIdx, subIdx) {
    menuState.selected = { parentIdx, subIdx };
    renderPhoneMenu();
    showMenuForm(menuState.selected);
}

// ---- 右侧表单 ----
function showMenuForm(sel) {
    const placeholder = document.getElementById('menu-form-placeholder');
    const formContent = document.getElementById('menu-form-content');
    const typeSection = document.getElementById('menu-type-section');

    if (!sel) {
        placeholder.style.display = '';
        formContent.style.display = 'none';
        return;
    }

    placeholder.style.display = 'none';
    formContent.style.display = '';

    const item = getSelectedItem(sel);
    if (!item) return;

    document.getElementById('menu-item-name').value = item.name || '';

    const hasSubs = sel.subIdx === -1 && (item.sub_button || []).length > 0;
    if (hasSubs) {
        // 一级菜单有子菜单，不显示类型选择
        typeSection.style.display = 'none';
    } else {
        typeSection.style.display = '';
        const type = item.type || 'click';
        const radio = document.querySelector(`input[name="menu-msg-type"][value="${type}"]`);
        if (radio) radio.checked = true;
        updateMenuTypeSections(type, item);
    }
}

function getSelectedItem(sel) {
    if (!sel) return null;
    const parent = menuState.draft.button[sel.parentIdx];
    if (!parent) return null;
    if (sel.subIdx === -1) return parent;
    return (parent.sub_button || [])[sel.subIdx] || null;
}

function onMenuItemNameChange() {
    const item = getSelectedItem(menuState.selected);
    if (!item) return;
    item.name = document.getElementById('menu-item-name').value;
    renderPhoneMenu();
}

function onMenuTypeChange() {
    const type = document.querySelector('input[name="menu-msg-type"]:checked')?.value || 'click';
    const item = getSelectedItem(menuState.selected);
    if (!item) return;
    item.type = type;
    // 清除其他字段
    delete item.key; delete item.url; delete item.media_id; delete item.appid; delete item.pagepath; delete item.article_id;
    updateMenuTypeSections(type, item);
}

function updateMenuTypeSections(type, item) {
    document.getElementById('menu-click-section').style.display = type === 'click' ? '' : 'none';
    document.getElementById('menu-view-section').style.display = type === 'view' ? '' : 'none';
    document.getElementById('menu-mini-section').style.display = type === 'miniprogram' ? '' : 'none';

    if (type === 'click') {
        const preview = document.getElementById('menu-click-preview');
        preview.textContent = item.key ? `KEY: ${item.key}` : '';
    } else if (type === 'view') {
        document.getElementById('menu-view-url').value = item.url || '';
    } else if (type === 'miniprogram') {
        document.getElementById('menu-mini-appid').value = item.appid || '';
        document.getElementById('menu-mini-pagepath').value = item.pagepath || '';
        document.getElementById('menu-mini-url').value = item.url || '';
    }
}

function onMenuItemFieldChange() {
    const item = getSelectedItem(menuState.selected);
    if (!item) return;
    const type = item.type || 'click';
    if (type === 'view') {
        item.url = document.getElementById('menu-view-url').value;
    } else if (type === 'miniprogram') {
        item.appid = document.getElementById('menu-mini-appid').value;
        item.pagepath = document.getElementById('menu-mini-pagepath').value;
        item.url = document.getElementById('menu-mini-url').value;
    }
}

// ---- 回复内容弹窗 ----
const replyTitles = { text: '回复文字', image: '回复图片', voice: '回复音频', video: '回复视频', article: '回复图文(外链)' };

function openReplyModal(type) {
    menuState.replyType = type;
    document.getElementById('reply-modal-title').textContent = replyTitles[type] || '回复内容';
    const body = document.getElementById('reply-modal-body');
    const item = getSelectedItem(menuState.selected);

    if (type === 'text') {
        body.innerHTML = `<div style="margin-bottom:8px;"><label style="color:#999; font-size:12px;">文字内容</label></div>
            <textarea id="reply-text-input" rows="4" placeholder="请输入回复文字"
                style="width:100%; padding:10px; background:#2d2d2d; border:1px solid #444; color:white; border-radius:6px; font-size:13px; box-sizing:border-box; resize:vertical;">${item && item.type === 'click' && item._replyText ? item._replyText : ''}</textarea>`;
    } else if (type === 'article') {
        body.innerHTML = `<div style="margin-bottom:8px;"><label style="color:#999; font-size:12px;">图文外链 URL</label></div>
            <input type="url" id="reply-article-url" placeholder="https://mp.weixin.qq.com/..."
                style="width:100%; padding:10px; background:#2d2d2d; border:1px solid #444; color:white; border-radius:6px; font-size:13px; box-sizing:border-box;"
                value="${item && item.article_id ? item.article_id : ''}">`;
    } else {
        body.innerHTML = `<div style="margin-bottom:8px;"><label style="color:#999; font-size:12px;">素材 Media ID</label></div>
            <input type="text" id="reply-mediaid-input" placeholder="永久素材 media_id"
                style="width:100%; padding:10px; background:#2d2d2d; border:1px solid #444; color:white; border-radius:6px; font-size:13px; box-sizing:border-box;"
                value="${item && item.media_id ? item.media_id : ''}">`;
    }
    document.getElementById('reply-modal').classList.remove('hidden');
}

function closeReplyModal() {
    document.getElementById('reply-modal').classList.add('hidden');
}

function confirmReply() {
    const item = getSelectedItem(menuState.selected);
    if (!item) { closeReplyModal(); return; }
    const type = menuState.replyType;

    if (type === 'text') {
        const val = document.getElementById('reply-text-input').value.trim();
        item.type = 'click';
        item.key = `TEXT_${Date.now()}`;
        item._replyText = val; // 仅本地预览用
        document.getElementById('menu-click-preview').textContent = `文字: ${val.substring(0, 20)}${val.length > 20 ? '...' : ''}`;
    } else if (type === 'article') {
        const val = document.getElementById('reply-article-url').value.trim();
        item.type = 'article_id';
        item.article_id = val;
        document.getElementById('menu-click-preview').textContent = `图文: ${val.substring(0, 30)}`;
    } else {
        const val = document.getElementById('reply-mediaid-input').value.trim();
        item.type = 'media_id';
        item.media_id = val;
        document.getElementById('menu-click-preview').textContent = `素材ID: ${val.substring(0, 20)}`;
    }
    closeReplyModal();
}

// ---- 草稿 & 发布 ----
function saveMenuDraft() {
    // 草稿保存到 localStorage
    localStorage.setItem(`menu_draft_${menuState.configId}`, JSON.stringify(menuState.draft));
    showToast('草稿已保存', 'success');
}

function publishMenu() {
    // 先自动保存草稿
    localStorage.setItem(`menu_draft_${menuState.configId}`, JSON.stringify(menuState.draft));
    document.getElementById('publish-confirm-modal').classList.remove('hidden');
}

function closePublishConfirm() {
    document.getElementById('publish-confirm-modal').classList.add('hidden');
}

async function doPublishMenu() {
    closePublishConfirm();
    // 从草稿读取
    const draftStr = localStorage.getItem(`menu_draft_${menuState.configId}`);
    const draft = draftStr ? JSON.parse(draftStr) : menuState.draft;

    // 清理内部字段
    const cleanButtons = (btns) => btns.map(btn => {
        const b = { name: btn.name };
        if (btn.sub_button && btn.sub_button.length > 0) {
            b.sub_button = cleanButtons(btn.sub_button);
        } else {
            const type = btn.type || 'click';
            b.type = type;
            if (type === 'click') {
                // key 必须有值，只能字母数字下划线，不超过128字节
                const rawKey = btn.key || `MENU_${Date.now()}`;
                b.key = rawKey.replace(/[^A-Za-z0-9_]/g, '_').substring(0, 128);
            } else if (type === 'view') {
                b.url = btn.url || '';
            } else if (type === 'miniprogram') {
                b.appid = btn.appid || '';
                b.pagepath = btn.pagepath || '';
                if (btn.url) b.url = btn.url;
            } else if (type === 'media_id') {
                b.media_id = btn.media_id || '';
            } else if (type === 'article_id' || type === 'article_view_limited') {
                b.article_id = btn.article_id || '';
            } else {
                // 其他 click 类事件类型（scancode_push 等）
                if (btn.key) b.key = btn.key.substring(0, 128);
            }
        }
        return b;
    });

    const payload = { button: cleanButtons(draft.button || []) };

    try {
        const res = await fetch(`/api/wechat/configs/${menuState.configId}/menu`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${state.token}`, 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '发布失败');
        showToast('菜单发布成功', 'success');
    } catch (e) {
        showToast('发布失败: ' + e.message, 'error');
    }
}

function confirmDeleteMenu() {
    if (!confirm('确定要删除当前公众号的所有自定义菜单吗？此操作不可恢复。')) return;
    doDeleteMenu();
}

async function doDeleteMenu() {
    try {
        const res = await fetch(`/api/wechat/configs/${menuState.configId}/menu`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${state.token}` }
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '删除失败');
        showToast('菜单已删除', 'success');
        menuState.draft = { button: [] };
        menuState.selected = null;
        renderPhoneMenu();
        showMenuForm(null);
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
}
