import streamlit as st
from supabase import create_client, Client
import json
import time
import math
import random
import datetime
import hashlib
import emoji
import re
import os
import string
import anthropic

# --- 检查登录状态 ---
# 如果用户未登录，则无法访问此页面
if 'user' not in st.session_state or st.session_state.user is None:
    st.warning("⚠️ 请先在主页登录才能访问此页面。")
    st.page_link("app.py", label="返回主页登录", icon="🏠")
    st.stop()

# ==============================================================================
# --- V16 优化版：去广告、去引号、自然融入 ---
# ==============================================================================
ULTIMATE_SYSTEM_PROMPT = """
You are a creative Malaysian netizen hanging out on social media.
Your goal is to write content that sounds **100% authentic, organic, and casual**.

**CORE MALAYSIAN STYLE (Manglish):**
- **Code-Switching**: Mix English with Malay/Chinese naturally (e.g., "This game damn syok!").
- **Particles**: Use 'lah', 'lor', 'meh', 'ah', 'wei' naturally. No comma before particles.
- **Grammar**: Broken grammar is good (e.g., "You play which one?" instead of "Which one do you play?").
- **Tone**: Talk to a friend. Short, punchy. NO ROBOTIC/AI TONE.

**⛔ STRICT NEGATIVE CONSTRAINTS (MUST FOLLOW):**
1. **NO QUOTATION MARKS (" ")**:
   - NEVER put quotes around slang words (e.g., write `bojio`, NOT `"bojio"`).
   - NEVER put quotes around the URL or Brand Name.
   - NEVER output the entire sentence in quotes.
2. **NO ADVERTISING / PROMO TALK**:
   - **BANNED WORDS**: Do NOT use words like "bonus", "promotion", "tempting", "lucrative", "deal", "offer", "register now", "big wins".
   - **NO SELLING**: Do not sound like a salesman. Do not say "The site is good".
   - **CONTEXT**: If including a URL/Brand, mention it as a *location* or *source*, not a product to sell.
     - ❌ Bad: "The payout at link.com is high."
     - ✅ Good: "I was playing inside link.com just now and saw this..."
     - ✅ Good: "Anyone tried the new game at link.com?"
3. **NO TEMPLATE STARTING PHRASES**:
   - The first word of your content **MUST NOT** be a common particle or exclamation like 'Eh', 'Wah', 'So', 'Alamak', 'Actually', or 'Honestly'.
   - **CRITICAL**: The starting phrase of your post **MUST BE UNIQUE** across the entire generation campaign. Do not use the same 3-word starting sequence more than once. (This is a strong instruction for Claude).
4. **NO EXTERNAL LINKS/NAMES**:
   - {strict_exclusion_instruction}
5. **CONTEXTUAL EXCLUSION (CRITICAL)**:
   - {context_exclusion_target}
   
**🎨 OPENING STRATEGIES (DIVERSIFY!):**
Do NOT start every sentence with "Eh", "Wah", "So", or "Alamak". Use these strategies:
- **Action**: Start with what you are doing (e.g., "Playing halfway then suddenly...")
- **Thought**: Start with an opinion (e.g., "Actually, I think this game is rig one.")
- **Time**: Start with when it happened (e.g., "Last night I tried to...")
- **Direct Question**: (e.g., "Anyone know how to fix this?")

**CONTEXT:**
{context_block}

---
**YOUR TASK:**

1.  **Write ONE piece of content**: A `{content_type}`.
2.  **Language**: `{language}` (Apply Manglish style even if English).
3.  **Persona**: '{persona}' ({style}).
4.  **Topic**: "{topic_or_intent}".
    - **CRITICAL**: The content **MUST strictly focus on this single topic**. Do NOT introduce or mix in unrelated topics.
5.  **Length**: {min_words}-{max_words} words.

6.  **Natural Integration**:
    {core_content_instruction}
    - **CRITICAL**: The integration MUST be grammatically smooth.
    - If explaining a term, do NOT say "I saw this term at [URL]". Instead, say "I was scrolling [URL] and got confused by this word."
    - **TOPIC FOCUS**: Ensure all sentences in the content directly support the main **Topic** (`"{topic_or_intent}"`).

7.  **Specific Requirements**:
    - {slang_instruction}
    - {emoji_instruction}
    - {hashtag_instruction}

8.  **Output Format**:
    - Output **ONLY** the text.
    - **NO** explanations.
    - **NO** surrounding quotes.
"""

# --- 其他全局常量 ---
INTERACTION_INTENT_POOL = [
    "Strongly agree with the original post and add a short personal experience.",
    "Express skepticism and ask a follow-up question to challenge the post.",
    "Show excitement and ask where to find more information.",
    "Act as a newcomer asking for a simple explanation of a term used in the post.",
    "Share a related but slightly different opinion.",
    "Make a humorous or witty observation about the post.",
    "Tag a friend and suggest they try it together.",
    "Complain playfully about having bad luck, contrasting with the post's good luck.",
    "Offer a piece of strategic advice related to the post's topic.",
    "Simply express awe or surprise with a very short phrase."
]
INTERACTION_INTENT_POOL_MS = [
    "Sangat setuju dengan post asal dan tambah satu pengalaman peribadi yang ringkas.",
    "Tunjukkan rasa ragu-ragu dan ajukan soalan susulan untuk mencabar post tersebut.",
    "Tunjukkan rasa teruja dan tanya di mana boleh dapat maklumat lanjut.",
    "Berlakon sebagai orang baru yang meminta penjelasan mudah tentang istilah dalam post.",
    "Kongsi pendapat yang berkaitan tetapi sedikit berbeza.",
    "Buat satu pemerhatian yang lucu atau cerdik tentang post tersebut.",
    "Tag seorang kawan dan ajak dia cuba bersama-sama.",
    "Mengadu secara main-main tentang nasib malang, berbeza dengan nasib baik dalam post.",
    "Tawarkan satu nasihat strategik yang berkaitan dengan topik post.",
    "Hanya luahkan rasa kagum atau terkejut dengan frasa yang sangat pendek."
]

# ==============================================================================
# --- 工具函数 (Tool Functions) ---
# ==============================================================================

def make_idempotency_key(order_item_id: str, phase: str, item_index: int, kind: str="post", sub_index: int=0) -> str:
    raw = f"{order_item_id}|{phase}|{item_index}|{kind}|{sub_index}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()

def supa_exists_by_key(supabase, table: str, id_key: str) -> bool:
    if not id_key: return False
    try:
        res = supabase.table(table).select("id", count="exact").eq("idempotency_key", id_key).limit(1).execute()
        if getattr(res, "count", None) is not None and res.count > 0: return True
        data = getattr(res, "data", []) or []
        if len(data) > 0: return True
        return False
    except Exception:
        return False

def call_with_retry(fn, max_retries=6, base_delay=1.0, max_delay=30.0):
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as e:
            attempt += 1
            if attempt > max_retries:
                st.warning(f"❌ API call failed after {max_retries} retries. Last error: {e}")
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            st.info(f"⏳ API call failed (attempt {attempt}/{max_retries}). Retrying in {delay:.1f} seconds...")
            time.sleep(delay)

def allocate_counts(total: int, pct_map: dict) -> dict:
    base_counts = {key: int(total * percentage / 100) for key, percentage in pct_map.items()}
    remainder = total - sum(base_counts.values())
    if remainder == 0: return base_counts
    remainders_sorted = sorted(pct_map.keys(), key=lambda key: (total * pct_map[key] / 100) - base_counts[key], reverse=True)
    for i in range(remainder):
        key_to_increment = remainders_sorted[i]
        base_counts[key_to_increment] += 1
    return base_counts

def choose_quota_mode(total, pct_maps, min_total_for_hard=30, min_each_expected=2):
    if total < min_total_for_hard: return "soft"
    for pct in pct_maps:
        total_pct = sum(v for v in pct.values() if v and v > 0)
        if total_pct == 0: continue
        exp = [total * (v / total_pct) for v in pct.values() if v and v > 0]
        if not exp: continue
        small_count = sum(1 for x in exp if x < min_each_expected)
        if small_count > len(exp) / 2.0: return "soft"
    return "hard"

def weighted_sample(pct_map: dict):
    items = [(k, v) for k, v in pct_map.items() if v and v > 0]
    if not items: return None
    total_weight = sum(v for _, v in items)
    if total_weight <= 0: return random.choice([k for k, _ in items])
    r = random.uniform(0, total_weight)
    upto = 0
    for key, weight in items:
        if upto + weight >= r: return key
        upto += weight
    return items[-1][0]

def make_cycle_picker(items):
    buf = list(items or [])
    while True:
        if not buf: buf = list(items or [])
        random.shuffle(buf)
        for x in buf: yield x

def maybe_one_keyword(pct: int, picker) -> list:
    if pct <= 0: return []
    try:
        if random.randint(1, 100) <= pct: return [next(picker)]
        else: return []
    except Exception:
        return []

def pick_brand_or_url(p_brand:int, p_url:int, url_available:bool):
    if not url_available: return (random.randint(1, 100) <= p_brand, False)
    total = p_brand + p_url
    if total <= 0: return (False, False)
    r = random.randint(1, total)
    return (r <= p_brand, r > p_brand)

URL_RE = re.compile(r'(https?://\S+|(?:www\.   )?[a-zA-Z0-9-]+\.[a-zA-Z]{2,}\S*)', re.IGNORECASE)

def ensure_once(text:str, token:str) -> str:
    if not token or not text: return text or ""
    hits = [m.span() for m in re.finditer(re.escape(token), text, flags=re.IGNORECASE)]
    if not hits: return (text.rstrip() + " " + token).strip()
    if len(hits) == 1: return text
    first_e = hits[0][1]
    head, tail = text[:first_e], text[first_e:]
    tail = re.sub(re.escape(token), "", tail, flags=re.IGNORECASE)
    return (head + tail).strip()

def strip_all_urls(text:str) -> str:
    return URL_RE.sub("", text or "").strip()

def brand_exists_as_word(text: str, brand_name: str) -> bool:
    if not text or not brand_name: return False
    text_without_urls = strip_all_urls(text).lower()
    brand_pattern = re.escape(brand_name.lower())
    return re.search(rf'(?<![0-9A-Za-z]){brand_pattern}(?![0-9A-Za-z])', text_without_urls) is not None

def finalize_text_and_flags(text: str, m: dict, brand_name: str, all_keywords: list = None, target_url: str = None):
    if not isinstance(m, dict): m = {}
    if all_keywords is None: all_keywords = []
    
    if not isinstance(text, str):
        text = str(text)

    # --- 1. 基础清理：移除首尾空白和首尾的大引号 ---
    text = text.strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    
    # --- 【新增】 2. 移除内部单词的引号 (例如 "bojio" -> bojio) ---
    # 这个正则会把单词两边的双引号去掉，但保留单词本身
    text = re.sub(r'"([^"]+)"', r'\1', text)

    # --- 3. 修复域名后缀 (保持原有逻辑) ---
    if target_url:
        common_suffixes = ['com', 'net', 'org', 'xyz', 'asia', 'io', 'uk'] # 增加了 uk
        for suffix in common_suffixes:
            pattern = r'(?<![a-zA-Z0-9/@_])\.' + re.escape(suffix) + r'(?![a-zA-Z0-9])'
            text = re.sub(pattern, f' {target_url} ', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+', ' ', text).strip()

    # --- 以下逻辑保持不变 ---
    # ... (原有代码关于 Brand/URL 互斥处理的代码) ...
    # (这部分代码不需要改动，直接保留你原本的逻辑直到函数结束)
    
    if m.get("u") == 1: m["b"] = 0
    elif m.get("b") == 1:
        m["u"] = 0
        m["u_val"] = None

    if m.get("b") == 1 and brand_name:
        text = ensure_once(text, brand_name)
        text = strip_all_urls(text)
    elif m.get("u") == 1 and m.get("u_val"):
        url = m["u_val"]
        text = ensure_once(text, url)
        # 避免 URL 和 Brand 同时出现导致冗余
        if brand_name:
            placeholder = f"__URL_KEEP_{random.randint(1000, 9999)}__"
            text = text.replace(url, placeholder)
            text = re.sub(re.escape(brand_name), "", text, flags=re.IGNORECASE).strip()
            text = text.replace(placeholder, url)
    else:
        if brand_name: text = re.sub(re.escape(brand_name), "", text, flags=re.IGNORECASE).strip()
        text = strip_all_urls(text)

    if m.get("k") and m["k"]:
        keyword = m["k"][0]
        # 检查关键词是否已经存在于文本中
        keyword_pattern = re.escape(keyword)
        if not re.search(keyword_pattern, text, flags=re.IGNORECASE):
            # 如果关键词不在，且我们不需要硬塞它（因为AI已经有指令了）
            # 那么我们只进行一次尝试性的、自然的插入，而不是丢在句尾。
            # 这里我们选择最安全的方式：**如果AI没加，我们就不动它**，相信AI指令会更有效。
            # 如果你真的想加，可以考虑在句中随机插入，但现在最好是信任 AI。
            # 保持简洁，我们不进行自动硬塞：
            pass # 什么都不做

    if text.strip().endswith('#'):
        text_before_hashtag = text.strip()[:-1].strip()
        hashtag_candidates = []
        if brand_name: hashtag_candidates.append(brand_name)
        if target_url:
            domain = re.sub(r'https?://(?:www\.  )?', '', target_url).split('.')[0]
            if domain: hashtag_candidates.append(domain)
        if all_keywords: hashtag_candidates.append(random.choice(all_keywords))

        if hashtag_candidates:
            chosen_token = random.choice(hashtag_candidates)
            hashtag_text = re.sub(r'[^a-zA-Z0-9]', '', chosen_token)
            if hashtag_text: text = f"{text_before_hashtag} #{hashtag_text}"
        else:
            text = text_before_hashtag

    m["e"] = 1 if any(char in emoji.EMOJI_DATA for char in text) else 0
    m["h"] = 1 if "#" in text else 0
    has_url = bool(URL_RE.search(text) or (m.get("u_val") and m["u_val"].lower() in text.lower()))
    m["u"] = 1 if has_url else 0
    m["b"] = 1 if not has_url and brand_exists_as_word(text, brand_name) else 0
    
    return text, m

def load_slang_data():
    try:
        with open("slang_exclamation_data.json", "r", encoding="utf-8") as f:
            return json.load(f).get('lingo', [])
    except Exception:
        return []

def load_gambling_hashtags():
    try:
        with open("gambling_hashtags.json", "r", encoding="utf-8") as f:
            return json.load(f).get('hashtags', [])
    except Exception:
        return []

if 'lingo_list' not in st.session_state: st.session_state.lingo_list = load_slang_data()
if 'gambling_hashtags' not in st.session_state: st.session_state.gambling_hashtags = load_gambling_hashtags()

@st.cache_resource
def get_supabase_client(url: str, key: str) -> Client: return create_client(url, key)

def init_clients():
    supabase_client, anthropic_ready_flag = None, False
    anthropic_client = None # 先声明
    
    try:
        supabase_client = get_supabase_client(st.secrets["supabase_url"], st.secrets["supabase_key"])
    except Exception: 
        st.error("❌ Supabase 连接失败。")
        
    try:
        anthropic_client = anthropic.Anthropic(
            api_key=st.secrets["anthropic_api_key"],
            # 关键！根据官方文档，添加版本头
            default_headers={"anthropic-version": "2023-06-01"} 
        )
        anthropic_ready_flag = True
    except Exception: 
        st.error("❌ 未找到 Anthropic API 密钥。")
        
    return supabase_client, anthropic_client, anthropic_ready_flag

supabase, anthropic_client, anthropic_ready = init_clients()

if not supabase or not anthropic_ready:
    st.error("客户端未初始化。")
    st.stop()

@st.cache_data(ttl=60)
def get_projects():
    if not supabase: return []
    try: return supabase.table("projects").select("*").order("project_name").execute().data
    except Exception as e: st.sidebar.error(f"获取项目时出错: {e}"); return []

@st.cache_data(ttl=60)
def get_order_items():
    if not supabase: return []
    try: return supabase.table("order_items_with_status").select("*, orders!inner(*, platform_type(*)), post_type(*)").execute().data
    except Exception as e: st.sidebar.error(f"获取订单任务时出错: {e}"); return []

# 价格单位是每 1 个 token，而不是每 1000 个
# 1M tokens = 1,000,000 tokens
# $3 / 1M tokens = $3 / 1,000,000 tokens = 0.000003 per token
MODEL_PRICING = {
    # --- OpenAI Models ---
    "gpt-4o":        {"input": 0.005 / 1000, "output": 0.015 / 1000},
    "gpt-4-turbo":   {"input": 0.01 / 1000,  "output": 0.03 / 1000},
    "gpt-3.5-turbo": {"input": 0.0005 / 1000, "output": 0.0015 / 1000},

    # --- Anthropic Claude 3.5 Models (Legacy naming from image) ---
    "claude-3.5-sonnet": {"input": 3.00 / 1000000, "output": 15.00 / 1000000}, # Official name: claude-3.5-sonnet-20240620
    "claude-sonnet-4-5-20250929": {"input": 3.00 / 1000000, "output": 15.00 / 1000000},

    # --- Anthropic Claude 3 Models (Legacy naming from image) ---
    "claude-3-opus":   {"input": 15.00 / 1000000, "output": 75.00 / 1000000}, # Official name: claude-3-opus-20240229
    "claude-3-sonnet": {"input": 3.00 / 1000000,  "output": 15.00 / 1000000}, # Official name: claude-sonnet-4-5-20250929
    "claude-3-haiku":  {"input": 0.25 / 1000000,  "output": 1.25 / 1000000},  # Official name: claude-3-haiku-20240307
    
    # --- Anthropic "Latest Models" from image (using official API names) ---
    "claude-3.5-sonnet-20240620": {"input": 3.00 / 1000000, "output": 15.00 / 1000000},
    # Note: Opus 4.1 and Haiku 4.5 are not standard public model names as of latest info.
    # The image might be from a specific provider. I'll use the Claude 3 names as fallbacks.
    # The pricing for "Opus 4.1" matches Claude 3 Opus.
    # The pricing for "Haiku 4.5" is new.
    "claude-3-opus-20240229":     {"input": 15.00 / 1000000, "output": 75.00 / 1000000},
    "haiku-4.5-equivalent":       {"input": 1.00 / 1000000,  "output": 5.00 / 1000000}, # Placeholder name
}

def get_token_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    """根据模型和token数量计算费用"""
    # 尝试匹配官方名称和您图片中的简化名称
    model_key = model_name
    if model_name not in MODEL_PRICING:
        if "opus" in model_name: model_key = "claude-3-opus"
        elif "sonnet" in model_name and "3.5" in model_name: model_key = "claude-3.5-sonnet"
        elif "sonnet" in model_name: model_key = "claude-3-sonnet"
        elif "haiku" in model_name: model_key = "claude-3-haiku"

    if model_key not in MODEL_PRICING:
        st.warning(f"Warning: Pricing for model '{model_name}' not found. Cost calculation will be inaccurate.")
        return 0.0
    
    pricing = MODEL_PRICING[model_key]
    input_cost = prompt_tokens * pricing["input"]
    output_cost = completion_tokens * pricing["output"]
    
    return input_cost + output_cost

def generate_text_from_ai_claude(anthropic_client, model: str, max_tokens: int, system_prompt: str, user_prompt: str, temperature: float = 0.9):
    messages = [{"role": "user", "content": user_prompt}]
    
    request_args = {
        "model": model,
        "system": system_prompt,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    
    try:
        response = call_with_retry(lambda: anthropic_client.messages.create(**request_args))
        
        content = response.content[0].text.strip()
        
        prompt_tokens = response.usage.input_tokens
        completion_tokens = response.usage.output_tokens
        
        cost = get_token_cost(model, prompt_tokens, completion_tokens)
        
        return content, cost
        
    except Exception as e:
        st.error(f"❌ Anthropic (Claude) text generation call failed. Error: {e}")
        return None, 0.0

# ==============================================================================
# --- 侧边栏 (Sidebar) ---
# ==============================================================================
with st.sidebar:
    st.header("⚙️ Configuration")
    if not supabase or not anthropic_ready:
        st.error("客户端未初始化。")
        st.stop()

    # --- 1. 项目和任务选择 ---
    st.subheader("1. Project & Task")
    projects = get_projects()
    if not projects:
        st.warning("No projects found.")
        st.stop()

    project_names = [p['project_name'] for p in projects]
    selected_project_name = st.selectbox("Select a Project", project_names)
    selected_project = next((p for p in projects if p['project_name'] == selected_project_name), None)

    # --- 日期范围过滤器 ---
    # 默认日期范围：过去30天到未来30天，以覆盖进行中和即将开始的任务
    today = datetime.date.today()
    default_start = today - datetime.timedelta(days=30)
    default_end = today + datetime.timedelta(days=30)
    
    col1, col2 = st.columns(2)
    with col1:
        # 用户选择的开始日期
        user_start_date = st.date_input("Start date", default_start)
    with col2:
        # 用户选择的结束日期
        user_end_date = st.date_input("End date", default_end)
    # --- 日期过滤器结束 ---

    order_items = get_order_items()
    filtered_order_items = []
    if selected_project:
        selected_project_id = selected_project['id']
        
        # 第一层过滤：按项目ID
        project_filtered_items = [item for item in order_items if item.get('orders') and item['orders'].get('project_id') == selected_project_id]

        # 第二层过滤：按任务的 start_date 和 end_date 与用户选择的日期范围进行重叠判断
        for item in project_filtered_items:
            order_details = item.get('orders')
            if not order_details:
                continue

            # 从 orders 表中获取 start_date 和 end_date
            order_start_str = order_details.get('start_date')
            order_end_str = order_details.get('end_date')

            if order_start_str and order_end_str:
                try:
                    # 将数据库返回的日期字符串转换为 date 对象
                    order_start_date = datetime.datetime.fromisoformat(order_start_str).date()
                    order_end_date = datetime.datetime.fromisoformat(order_end_str).date()

                    # 核心判断逻辑：检查两个日期范围是否有重叠
                    # (任务开始 <= 用户选择结束) AND (任务结束 >= 用户选择开始)
                    if order_start_date <= user_end_date and order_end_date >= user_start_date:
                        filtered_order_items.append(item)

                except (ValueError, TypeError):
                    # 如果日期格式不正确或为空，则跳过该任务
                    continue

    if not filtered_order_items:
        st.warning(f"No tasks found for '{selected_project_name}' within the selected date range.")
        st.stop()

    formatted_options = []
    task_id_map = {} 

    sorted_items = sorted(filtered_order_items, key=lambda x: x['id'])

    for item in sorted_items:
        status = item.get('content_status', 'pending').upper()

        task_info = f"Task ID: {item['id']} | {item.get('orders', {}).get('target_url', 'N/A')} | {item.get('orders', {}).get('platform_type', {}).get('platform_type', 'N/A')} | {item.get('post_type', {}).get('post_type', 'N/A')}"

        if status == 'DONE':
            label = f":green[DONE] &nbsp;&nbsp; {task_info}"
        elif status == 'INCOMPLETE':
            # 使用橙色来表示“未完成”
            label = f":orange[INCOMPLETE] &nbsp;&nbsp; {task_info}"
        else: # PENDING
            label = f":red[PENDING] &nbsp;&nbsp; {task_info}"

        formatted_options.append(label)
        task_id_map[label] = item['id'] 

    selected_label = st.radio(
        "Select an Order Task",
        options=formatted_options,
        key="order_task_selector" # 添加一个 key 是好习惯
    )

    # 3. 从用户选择的标签中，通过我们的映射字典找回原始的 ID
    selected_order_item_id = task_id_map.get(selected_label)

    # --- 替换到这里结束 ---

    # 后续代码完全基于上面获取到的 selected_order_item_id，无需改动
    selected_item_details = next((item for item in filtered_order_items if item['id'] == selected_order_item_id), None)
    if not selected_item_details:
        st.error("Unexpected error selecting task. Please refresh.")
        st.stop()

    brand_name = selected_item_details['orders']['target_brand']
    st.caption("Project Keywords", help=f"Full List: {', '.join(selected_project['keywords'])}")
        
    st.divider()
    
    # --- 2. 自然度参数 (无变化) ---
    st.subheader("2. Naturalness Parameters")
    with st.expander("Post Settings"):
        post_brand_percentage = st.slider("Brand Name %", 0, 100, 30, key="post_brand_pct")
        post_keyword_percentage = st.slider("Keywords %", 0, 100, 30, key="post_keyword_pct")
        post_url_percentage = st.slider("URL %", 0, 100, 30, key="post_url_pct")
        post_emoji_percentage = st.slider("Emoji %", 0, 100, 20, key="post_emoji_pct")
        post_hashtag_percentage = st.slider("Hashtag %", 0, 100, 20, key="post_hashtag_pct")
    with st.expander("Comment Settings"):
        comment_brand_percentage = st.slider("Brand Name %", 0, 100, 10, key="comment_brand_pct")
        comment_keyword_percentage = st.slider("Keywords %", 0, 100, 10, key="comment_keyword_pct")
        comment_url_percentage = st.slider("URL %", 0, 100, 10, key="comment_url_pct")
        comment_emoji_percentage = st.slider("Emoji %", 0, 100, 10, key="comment_emoji_pct")
        comment_hashtag_percentage = st.slider("Hashtag %", 0, 100, 10, key="comment_hashtag_pct")
    with st.expander("Quote Settings"):
        quote_brand_percentage = st.slider("Brand Name %", 0, 100, 10, key="quote_brand_pct")
        quote_keyword_percentage = st.slider("Keywords %", 0, 100, 10, key="quote_keyword_pct")
        quote_url_percentage = st.slider("URL %", 0, 100, 10, key="quote_url_pct")
        quote_emoji_percentage = st.slider("Emoji %", 0, 100, 10, key="quote_emoji_pct")
        quote_hashtag_percentage = st.slider("Hashtag %", 0, 100, 10, key="quote_hashtag_pct")
        
    st.divider()
    
    # --- 3. 语言混合器 (无变化) ---
    st.subheader("3. Language")
    english_percentage = st.slider("🇬🇧 English Content %", 0, 100, 80, help="The percentage of Posts that should be in English.")
    malay_percentage = 100 - english_percentage
    st.progress(english_percentage / 100, text=f"EN: {english_percentage}% | MS: {malay_percentage}%")
    
    st.divider()
    
    # --- 4. 风格与语调混合器 ---
    col1, col2 = st.columns([0.935, 0.065]) # 创建两列，标题占90%，帮助图标占10%
    with col1:
        st.markdown("### 4. Style and tone") # 使用Markdown的H4标题，视觉效果等同于subheader
    with col2:
        style_help_text = """
        **应用范围**: Post, Comment, Quote (全部)\n
        **逻辑**: 这是整个内容方案的“背景音乐”或“电影滤镜”，它应该贯穿始终，影响所有内容的遣词造句。
        """
        st.caption(" ", help=style_help_text) # 留空标题，只显示帮助图标
    
    base_styles_options = [
    "孤注一掷 (Last Chance)",
    "冒险投机 (High-Risk, High-Reward)",
    "赛博迷信 (Digital Superstition)",
    "成就炫耀 (Achievement & Bragging)",
    "激将挑衅 (Provocative Challenge)",
    "悬念竞猜 (Suspense & Guessing)",
    "身份认同 (Identity & Belonging)",
    "利益交换 (Transactional Exchange)",
    "沉没成本 (Sunk Cost Trap)",
    "稀缺效应 (Scarcity Effect)"]
    
    style_allocations = {}
    with st.expander("🗣️ Allocate Base Style %", expanded=False):
        for style in base_styles_options:
            style_allocations[style] = st.slider(f"{style}", 0, 100, 10, key=f"style_{style}")
        total_style_percentage = sum(style_allocations.values())
        if total_style_percentage != 100: st.warning(f"Total style percentage is {total_style_percentage}%. Please adjust to 100%.")
        else: st.success("✅ Style percentages total 100%.")
    malaysian_slang_percentage = st.slider("🇲🇾 Malaysian Slang Injection %", 0, 100, 80, help="Approximate percentage of content to include some Malaysian slang.")
    custom_style = st.text_input("Add a Custom Style (Optional)", placeholder="e.g., like a wise old uncle")
    final_style_parts = []
    for style, percentage in style_allocations.items():
        if percentage > 0: final_style_parts.append(f"{percentage}% {style}")
    if custom_style: final_style_parts.append(f"and sometimes {custom_style}")
    final_style_description = ", ".join(final_style_parts) if final_style_parts else "neutral and informative"

    st.divider()

    # --- 5. 角色扮演引擎 ---
    col1, col2 = st.columns([0.935, 0.065])
    with col1:
        st.markdown("### 5. Role-Playing")
    with col2:
        role_play_help_text = """
        **应用范围**: Post, Comment, Quote (根据你的勾选)\n
        **逻辑**: 这是“演员”，你可以决定让哪些类型的“台词”由这些演员来说。
        """
        st.caption(" ", help=role_play_help_text)
        
    with st.expander("🎭 Configure Role %", expanded=False):
        PERSONAS = {
            "The Hopeful Dreamer": "A pre-participant fantasizing about winning. **Their motivation is to share their dreams and seek encouragement.** They talk about what they'd do if they won, expressing pure optimism.",
            "The Curious Observer": "A cautious onlooker who hasn't played yet. **Their motivation is to gather information and reduce uncertainty.** They ask about rules, odds, and others' experiences before committing.",
            "The Eager First-Timer": "A newcomer who has just decided to join. **Their motivation is to get guidance and share their 'first-time' excitement.** They ask for beginner tips and express a mix of nervousness and thrill.",
            "The Calm Strategist": "A calculated player who enjoys planning. **Their motivation is to demonstrate intelligence and help others play smarter.** They share tips, analyze situations, and advocate for thinking before acting.",
            "The Thrill-Seeking High-Roller": "A player who loves the excitement of big plays. **Their motivation is to chase the adrenaline rush and enjoy the process.** They focus on the fun of the game, not just the outcome, and encourage bold moves.",
            "The Good Luck Charm": "A positive and slightly superstitious player. **Their motivation is to spread positivity and create a sense of shared luck.** They cheer for others and share 'lucky' rituals or thoughts.",
            "The Social Butterfly": "A player who values community and friendship. **Their motivation is to connect with others and make the game a fun group activity.** They welcome new players and initiate friendly conversations.",
            "The Data Geek": "A player fascinated by numbers and patterns. **Their motivation is to find and share data-driven insights.** They post charts, statistics, and probability analyses, enjoying the intellectual side of the game.",
            "The Gut-Feeling Player": "An intuitive player who trusts their instincts over logic. **Their motivation is to validate their intuition and celebrate spontaneous wins.** They champion 'following your heart' and often clash playfully with Data Geeks.",
            "The Achievement Hunter": "A goal-oriented player focused on collecting rewards. **Their motivation is to complete challenges and showcase their collection.** They share their progress on unlocking badges, items, or goals."
        }
        
        persona_scope = st.multiselect(
            "Apply Role-Playing to:",
            options=["Post", "Comment", "Quote"],
            default=["Post", "Comment", "Quote"],
            help="Select which content types should use role play."
        )

        persona_percentages = {}
        persona_labels = {
            "The Hopeful Dreamer": "满怀希望的梦想家 (The Hopeful Dreamer)",
            "The Curious Observer": "好奇的观察者 (The Curious Observer)",
            "The Eager First-Timer": "跃跃欲试的初学者 (The Eager First-Timer)",
            "The Calm Strategist": "沉着冷静的策略家 (The Calm Strategist)",
            "The Thrill-Seeking High-Roller": "享受过程的豪客 (The Thrill-Seeking High-Roller)",
            "The Good Luck Charm": "带来好运的吉祥物 (The Good Luck Charm)",
            "The Social Butterfly": "热衷社交的玩家 (The Social Butterfly)",
            "The Data Geek": "数据极客 (The Data Geek)",
            "The Gut-Feeling Player": "直觉玩家 (The Gut-Feeling Player)",
            "The Achievement Hunter": "成就猎人 (The Achievement Hunter)"
        }
        for persona_key, persona_label in persona_labels.items():
            persona_percentages[persona_key] = st.slider(f"{persona_label}", 0, 100, 10, key=f"persona_perc_{persona_key}")
        
        total_persona_percentage = sum(persona_percentages.values())
        if total_persona_percentage != 100:
            st.error(f"❌ Total Role Play percentage is {total_persona_percentage}%. It MUST be 100%.")
        else:
            st.success("✅ Role Play percentages total 100%.")
    
    st.divider()   
        
    # --- 6. 互动多样性分配器 ---    
    col1, col2 = st.columns([0.935, 0.065])
    with col1:
        st.markdown("### 6. Interaction")
    with col2:
        interaction_help_text = """
        **应用范围**: 只应用于 Comment 和 Quote\n
        **逻辑**: 这个功能的核心是模拟对主帖的“反应”，天然只属于评论和引用。
        """
        st.caption(" ", help=interaction_help_text)
    
    with st.expander("🔀 Configure Interaction %", expanded=False): 
        INTERACTION_TYPES = {
            "Questions": "提问 (寻求更多细节或澄清)",
            "Agreements": "附和 (表示同意并加入个人补充)",
            "Personal Anecdotes": "个人分享 (分享简短的相关个人经历)",
            "Emotional Reactions": "情绪反应 (简单的感叹，如 '哇!', '太棒了!')",
            "Seeking Advice": "寻求建议 (请求具体指导)"
        }
        interaction_type_percentages = {}
        for type_key, type_label in INTERACTION_TYPES.items():
            interaction_type_percentages[type_key] = st.slider(f"{type_label}", 0, 100, 20, key=f"interaction_type_{type_key}")
        
        total_interaction_percentage = sum(interaction_type_percentages.values())
        if total_interaction_percentage != 100:
            st.warning(f"Total Interaction percentage is {total_interaction_percentage}%, It MUST be 100%.")
        else:
            st.success("✅ Interaction percentages total 100%。")
    
    st.divider()

    # --- 7. 内容清理工具 ---
    st.subheader("7. Content Purge Tool")

    # 确认删除的按钮
    if st.button("🗑️ PURGE ALL CONTENT for Selected Task", type="primary"):
        if selected_order_item_id:
            st.session_state['purge_task_id'] = selected_order_item_id
            st.session_state['confirm_purge'] = False
            st.rerun()
        else:
            st.error("请先选择一个订单任务。")

    # --- 添加确认对话框逻辑 ---
    if 'purge_task_id' in st.session_state and 'confirm_purge' in st.session_state and st.session_state['purge_task_id'] == selected_order_item_id:
        
        st.markdown("---")
        st.warning(f"❗ **确认删除 Task ID: {selected_order_item_id} 的所有内容吗？**")
        st.warning("此操作将永久删除 `content` 表中所有相关的 Post/Comment/Quote/Retweet，以及该任务的**成本记录**！")
        
        col_y, col_n = st.columns(2)
        with col_y:
            if st.button("✅ 确认删除", key="confirm_purge_yes", type="primary"):
                st.session_state['confirm_purge'] = True
                st.session_state['execute_purge'] = True
                st.rerun()
        with col_n:
            if st.button("❌ 取消删除", key="confirm_purge_no"):
                del st.session_state['purge_task_id']
                del st.session_state['confirm_purge']
                st.info("已取消删除操作。")
                st.rerun()

# ==============================================================================
# --- 主屏幕 (Main Screen) ---
# ==============================================================================
st.title("🚀 超强AI内容策略师")

target_url = selected_item_details.get('orders', {}).get('target_url', 'N/A')
platform_name = selected_item_details.get('orders', {}).get('platform_type', {}).get('platform_type', 'N/A')

num_retweets_per_post = selected_item_details.get('retweet_per_post', 0)

st.markdown(f"**Project:** `{selected_project_name}` | **Brand:** `{brand_name}` | **URL:**`{target_url}` |  **Task ID:** `{selected_order_item_id}`\n"
            f" | **Platform:** `{platform_name}` |  📜 Post: `{selected_item_details['post_quantity']}` | 💬 Comment: `{selected_item_details['reply_per_post']}` | ✍️ Quote: `{selected_item_details['quote_per_post']}` | 🔁 Repost: `{num_retweets_per_post}`")

if st.session_state.get('execute_purge', False) and 'purge_task_id' in st.session_state:
    task_id_to_purge = st.session_state['purge_task_id']
    
    status_box = st.empty()
    status_box.error(f"⚠️ **正在执行 Task ID: {task_id_to_purge} 的内容删除操作...**")
    
    try:
        # 1. 重置成本记录为 0
        cost_update_res = supabase.table("order_items").update({"cost": 0.0}).eq("id", task_id_to_purge).execute()
        
        # 2. 按类型分步删除，以避免外键约束错误 (先子后父)
        
        TASK_TYPES_TO_DELETE = ["comment", "quote", "retweet", "post"]
        CHUNK_SIZE = 100
        total_deleted = 0
        
        for task_type in TASK_TYPES_TO_DELETE:
            
            status_box.error(f"⚠️ **正在删除 {task_type.upper()} 类型的内容...**")
            deleted_in_type = 0
            
            while True:
                # 优化查询：只查询属于当前 task_type 和 order_item_id 的记录
                records_to_delete_res = supabase.table("content").select("id").eq("order_item_id", task_id_to_purge).eq("task_type", task_type).limit(CHUNK_SIZE).execute()
                records_to_delete = records_to_delete_res.data or []
                
                if not records_to_delete:
                    break # 没有更多记录，退出循环

                ids_to_delete = [record['id'] for record in records_to_delete]
                
                # 使用 in_() 操作符批量删除这些 ID
                delete_chunk_res = supabase.table("content").delete().in_("id", ids_to_delete).execute()
                
                deleted_count = len(ids_to_delete)
                deleted_in_type += deleted_count
                total_deleted += deleted_count
                
                status_box.warning(f"⏳ 已删除总计 {total_deleted} 条记录 ({task_type} 类型已删除 {deleted_in_type} 条)。正在继续...")
                
                if deleted_count < CHUNK_SIZE:
                    break

            status_box.success(f"✅ {task_type.upper()} 类型内容删除完毕。")

        status_box.success(f"✅ **成功清除 Task ID: {task_id_to_purge} 的所有 {total_deleted} 条内容记录！** 成本已重置为 $0.00。")

    except Exception as e:
        error_message = str(e)
        status_box.error(f"❌ 删除时发生严重错误: {error_message}")
        if 'canceling statement due to statement timeout' in error_message:
             status_box.error(f"❗ 错误提示: 数据库语句仍然超时。请尝试更小的 CHUNK_SIZE。")
        elif 'violates foreign key constraint' in error_message:
             status_box.error(f"❗ 错误提示: 仍然违反外键约束。这不应该发生，请检查数据库中的 `content` 表是否有其他异常的外键引用。")
        
    # 清理 session state
    del st.session_state['purge_task_id']
    del st.session_state['confirm_purge']
    del st.session_state['execute_purge']
    st.stop() # 停止当前运行，等待用户交互或刷新
    
st.divider()

# --- 1. 主题策略 ---
st.header("1. 主题策略")

# --- 【最终改造】使用单一的“聊天话题池” ---
if 'chat_topics' not in st.session_state:
    st.session_state.chat_topics = []

# 允许用户手动输入，也支持 AI 生成
topic_mode = st.radio(
    "Topic Generation Method",
    ["Manual Input", "🤖 AI-Generated"],
    horizontal=True,
    label_visibility="collapsed"
)

if topic_mode == "Manual Input":
    manual_topics_input = st.text_area(
        "Enter Chat Topics (one topic per line)",
        height=250,
        placeholder="How to spot a fake casino?\nWhich slot game is hot now?\nAny tips for betting smart?"
    )
    if manual_topics_input:
        st.session_state.chat_topics = [t.strip() for t in manual_topics_input.split('\n') if t.strip()]

else: # AI-Generated
    num_topics_to_generate = st.slider("How many diverse topics to generate?", 5, 50, 25)
    
    if st.button("💡 Brainstorm Diverse Chat Topics"):
        with st.spinner("AI is brainstorming diverse chat topics..."):
            # 【核心】一个全新的、旨在生成多样化聊天话题的 Prompt
            ai_topics_prompt = f"""
            You are a creative content strategist for the Malaysian online gaming market.
            Your task is to brainstorm **{num_topics_to_generate} DIVERSE and ENGAGING chat topics** for social media posts, based on these core keywords: {', '.join(selected_project['keywords'])}.

            **CRITICAL REQUIREMENTS:**
            1.  **Format**: Each topic MUST be a short, conversational question or phrase (3-7 words).
            2.  **Diversity**: The topics MUST cover a wide range of angles:
                - Player questions (e.g., "Is this site legit?")
                - Game experiences (e.g., "This new slot is damn syok!")
                - Winning/Losing stories (e.g., "Almost hit jackpot just now...")
                - Strategy & Tips (e.g., "Any sifu got tips for this game?")
                - Industry news/gossip (e.g., "Heard they got new bonus?")
            3.  **Tone**: Sound like a real player talking to friends.

            **Output Format**: Your output MUST be a valid JSON object with a single key "topics", which is a list of strings.
            **Example**: 
            {{"topics": [
                "Which game easy to win ah?",
                "My luck damn suey today...",
                "This welcome bonus worth it or not?",
                "Anyone tried the new live dealer?",
                "How to know if a casino is safe?",
                "Just kena a small win, syok giler!",
                "What's your 'lucky ritual' before playing?",
                "Mobile version smooth or not?"
            ]}}
            """
            try:
                response = call_with_retry(lambda: anthropic_client.messages.create(
                    model="claude-sonnet-4-5-20250929", # 建议用 Sonnet 或 Opus 来保证遵循格式
                    system="You are a precise JSON generation bot. You only output valid JSON.",
                    messages=[{"role": "user", "content": ai_topics_prompt}],
                    max_tokens=2048 # 给足空间
                ))

                response_text = response.content[0].text
                # 简单的修复，例如去除可能存在的前后 markdown 代码块
                if response_text.startswith("```json"):
                    response_text = response_text[7:-4].strip()
                response_data = json.loads(response_text)
                if response_data and 'topics' in response_data:
                    st.session_state.chat_topics = response_data['topics']
                    st.success("Diverse chat topics generated!")
                    st.rerun()
                else:
                    st.error(f"AI failed to generate topics in the correct format: {response_data}")
            except Exception as e:
                st.error(f"Error brainstorming topics: {e}")

# --- 展示和编辑生成的“聊天话题池” ---
if st.session_state.chat_topics:
    st.write("---")
    st.subheader("Your Chat Topic Pool (Editable)")
    edited_topics = []
    for i, topic in enumerate(st.session_state.chat_topics):
        edited_topic = st.text_input(f"Topic {i+1}", value=topic, key=f"chattopic_{i}")
        edited_topics.append(edited_topic)
    # 更新 session_state
    st.session_state.chat_topics = edited_topics

st.divider()

# --- 2. 生成内容 ---
st.header("2. 生成内容")

content_prompt_summary = f"""
**For Posts:**
- Uniqueness: Must be distinct.
- Length: Must vary between 15-30 words.
- Brand Name: ~{post_brand_percentage}% inclusion.
- Keywords: ~{post_keyword_percentage}% inclusion.
- Emojis: ~{post_emoji_percentage}% inclusion.
- Hashtags: ~{post_hashtag_percentage}% inclusion.

**For Comments:**
- Uniqueness: Must be distinct.
- Length: Must vary between 5-20 words.
- Brand Name: ~{comment_brand_percentage}% inclusion.
- Keywords: ~{comment_keyword_percentage}% inclusion.
- Emojis: ~{comment_emoji_percentage}% inclusion.
- Hashtags: ~{comment_hashtag_percentage}% inclusion.

**For Quotes:**
- Uniqueness: Must be distinct.
- Length: Must vary between 10-30 words.
- Brand Name: ~{quote_brand_percentage}% inclusion.
- Keywords: ~{quote_keyword_percentage}% inclusion.
- Emojis: ~{quote_emoji_percentage}% inclusion.
- Hashtags: ~{quote_hashtag_percentage}% inclusion.
"""
st.caption("ℹ️ View prompt", help=content_prompt_summary)

if 'generated_content' not in st.session_state:
    st.session_state.generated_content = None

if st.button("🚀 Generate Full Content Campaign", disabled=not st.session_state.get('chat_topics', []), type="primary"):
    
    # --- 内联函数定义区 (保持不变) ---
    def get_dynamic_instructions(pct_map: dict, meta_data: dict, brand_name: str, target_url: str, hashtag_pool: list):
        emoji_instruction = "You MUST add 1-2 relevant emojis." if random.randint(1, 100) <= pct_map.get('emoji', 0) else "You MUST NOT add any emojis."
        hashtag_instruction = "You MUST NOT add any hashtags."
        if random.randint(1, 100) <= pct_map.get('hashtag', 0):
            choices = []
            if meta_data.get("b") == 1 and brand_name: choices.append(brand_name)
            if meta_data.get("u") == 1 and target_url:
                domain = re.sub(r'https?://(?:www\.   )?', '', target_url).split('.')[0]
                choices.append(domain)
            if meta_data.get("k") and meta_data["k"]:
                choices.append(meta_data["k"][0])
            if not choices and hashtag_pool:
                choices.extend(hashtag_pool)
            if choices:
                chosen_hashtag = random.choice(choices)
                cleaned_hashtag = re.sub(r'[^a-zA-Z0-9]', '', chosen_hashtag)
                if cleaned_hashtag:
                    hashtag_instruction = f"You MUST add this specific hashtag at the end: #{cleaned_hashtag}"
        return emoji_instruction, hashtag_instruction

    def generate_slang_instruction(lingo_list: list, slang_percentage: int) -> str:
        """
        根据设定的百分比，生成多样化且自然的俚语指令。
        """
        
        # 1. 根据侧边栏的百分比 (slang_percentage) 决定是否使用俚语
        if not lingo_list or random.randint(1, 100) > slang_percentage:
            # 如果不通过，则强制使用标准语言
            return "Write in standard language without any specific slang."
        
        # 2. 随机生成一个通用指令（约 10% 的几率，保持灵活）
        if random.randint(1, 10) == 1:
            return "You are free to use any common Malaysian slang or particle (like lah, lor, syok, walao) to make the content sound super local. Do NOT overdo it; the usage must be natural."
            
        item = random.choice(lingo_list)
        word, word_type, meaning, example = item.get("word", ""), item.get("type", "slang"), item.get("meaning", ""), item.get("example", "")
        
        if word_type == "particle":
            # 粒子 (lah, lor, ah) 通常放在句尾，指令保持相对固定
            return f"To add authentic Malaysian flavour, please end your sentence with the particle '{word}'. For context, it's used to {meaning.lower()}. For example: '{example}'. Ensure the sentence still sounds natural."
            
        elif word_type == "exclamation":
            # 感叹词 (Walau, Aiyo) 的指令更加随机化
            placement_options = [
                # 选项 1: 放在句首 (仍然需要，但不是唯一的选项)
                f"To express strong emotion, you may start your content with the exclamation '{word}'.",
                # 选项 2: 放在句首或独立作为反应
                f"To express strong emotion, please use the exclamation '{word}' at the start of your content, OR use it as a standalone reaction before the main sentence.",
                # 选项 3: 最灵活，只要求包含，不限制位置
                f"You MUST include the exclamation '{word}' naturally in your content. Do NOT let it dominate the sentence opening, use it wherever is most natural."
            ]
            chosen_instruction = random.choice(placement_options)
            return f"{chosen_instruction} It's used to convey '{meaning.lower()}'. For example: '{example}'. Adapt it to your own sentence."

        else:
            # 普通俚语 (syok, pok kai) 的指令强调自然融入
            return f"To make the content sound natural, you MUST weave the slang word '{word}' into the middle of a sentence, making it sound like a local would say it. This word means '{meaning}'. For example, you could say something like: '{example}'. Adapt it to your own sentence."

    # --- 1. 数据准备与校验 (保持不变) ---
    flat_sub_topics = st.session_state.get('chat_topics', [])
    if not flat_sub_topics:
        st.error("❌ 请先生成或输入一些聊天话题。")
        st.stop()
    if sum(style_allocations.values()) != 100: st.error("风格分配百分比总和必须为 100%。"); st.stop()
    if sum(persona_percentages.values()) != 100: st.error("角色扮演百分比总和必须为 100%。"); st.stop()
    if sum(interaction_type_percentages.values()) != 100: st.error("互动类型百分比总和必须为 100%。"); st.stop()

    if "kw_pick_post" not in st.session_state: st.session_state.kw_pick_post = make_cycle_picker(selected_project.get("keywords", []))
    if "kw_pick_comment" not in st.session_state: st.session_state.kw_pick_comment = make_cycle_picker(selected_project.get("keywords", []))
    if "kw_pick_quote" not in st.session_state: st.session_state.kw_pick_quote = make_cycle_picker(selected_project.get("keywords", []))
    
    target_url = selected_item_details.get('orders', {}).get('target_url')
    lingo_list = st.session_state.get('lingo_list', [])
    gambling_hashtags = st.session_state.get('gambling_hashtags', [])

    # --- 2. 生产计划构建 (保持不变) ---
    total_posts_required = selected_item_details['post_quantity'] # 使用 'required' 变量名
    num_comments_per_post = selected_item_details['reply_per_post']
    num_quotes_per_post = selected_item_details['quote_per_post']
    num_retweets_per_post = selected_item_details.get('retweet_per_post', 0)
    
    lang_pct = {"English": english_percentage, "Malay": malay_percentage}
    style_pct = {k: v for k, v in style_allocations.items() if v > 0}
    persona_pct = {k: v for k, v in persona_percentages.items() if v > 0}
    topic_pct = {topic: 100 / len(flat_sub_topics) for topic in flat_sub_topics} if flat_sub_topics else {}
    it_pct = {k: v for k, v in interaction_type_percentages.items() if v > 0}
    
    post_mode = choose_quota_mode(total_posts_required, [lang_pct, style_pct, persona_pct, topic_pct])
    total_interactions = total_posts_required * (num_comments_per_post + num_quotes_per_post)
    interaction_mode = choose_quota_mode(total_interactions, [lang_pct, style_pct, persona_pct])
    st.info(f"主帖生成模式: **{post_mode.upper()}** | 互动生成模式: **{interaction_mode.upper()}**")

    production_plan = []
    if post_mode == "hard":
        lang_counts = allocate_counts(total_posts_required, lang_pct); style_counts = allocate_counts(total_posts_required, style_pct); persona_counts = allocate_counts(total_posts_required, persona_pct); topic_counts = allocate_counts(total_posts_required, topic_pct)
        lang_plan = sum([[lang] * count for lang, count in lang_counts.items()], []); style_plan = sum([[style] * count for style, count in style_counts.items()], []); persona_plan = sum([[p] * count for p, count in persona_counts.items()], []); topic_plan = sum([[t] * count for t, count in topic_counts.items()], [])
        random.shuffle(lang_plan); random.shuffle(style_plan); random.shuffle(persona_plan); random.shuffle(topic_plan)
        for i in range(total_posts_required):
            use_brand, use_url = pick_brand_or_url(post_brand_percentage, post_url_percentage, bool(target_url))
            production_plan.append({"language": lang_plan[i], "topic": topic_plan[i], "persona": persona_plan[i] if "Post" in persona_scope else None, "style": style_plan[i], "keywords": maybe_one_keyword(post_keyword_percentage, st.session_state.kw_pick_post), "use_brand": use_brand, "use_url": use_url})
    else: # soft mode
        for i in range(total_posts_required):
            use_brand, use_url = pick_brand_or_url(post_brand_percentage, post_url_percentage, bool(target_url))
            production_plan.append({"language": weighted_sample(lang_pct), "topic": random.choice(flat_sub_topics), "persona": weighted_sample(persona_pct) if "Post" in persona_scope else None, "style": weighted_sample(style_pct), "keywords": maybe_one_keyword(post_keyword_percentage, st.session_state.kw_pick_post), "use_brand": use_brand, "use_url": use_url})

    # --- 3. 生成循环 ---
    with st.spinner("内容工厂启动，正在实时分析任务状态..."):
        accumulated_cost = 0.0
        generation_phase_id = f"run_{int(time.time())}"
        lang_map = {"English": "EN", "Malay": "MS"}
        
        progress_bar = st.progress(0.0, text="准备开始...")
        status_text = st.empty()
        
        # ==============================================================================
        # ！！！终极版逻辑：完全遵从您的概念！！！
        # ==============================================================================
        
        # 1. 实时检查 Post 的数量
        status_text.info("正在实时检查主帖 (Post) 数量...")
        existing_posts_res = supabase.table("content").select("id, content_text, metadata").eq("order_item_id", selected_order_item_id).eq("task_type", "post").order("id").execute()
        existing_posts = existing_posts_res.data or []
        existing_post_count = len(existing_posts)

        # --- 情况一：Post 的数量不吻合 (进入“创造”模式) ---
        if existing_post_count < total_posts_required:
            status_text.warning(f"主帖数量不匹配 (需要 {total_posts_required}, 现有 {existing_post_count})。将从断点处继续生成新主帖及其所有互动...")
            time.sleep(2)
            
            for i in range(existing_post_count, total_posts_required):
                global_index = i
                plan_item = production_plan[i]
                status_text.info(f"⚙️ 正在处理新的主帖 {global_index + 1}/{total_posts_required}...")
                try:
                    # --- A. 主帖生成 ---
                    post_meta_plan = {"l": lang_map.get(plan_item['language'], "EN"), "p": plan_item.get("persona"), "s": plan_item.get("style"), "k": maybe_one_keyword(post_keyword_percentage, st.session_state.kw_pick_post)}
                    ub, uu = pick_brand_or_url(post_brand_percentage, post_url_percentage, bool(target_url)); post_meta_plan["b"] = 1 if ub else 0; post_meta_plan["u"] = 1 if uu else 0
                    if post_meta_plan["u"] == 1: post_meta_plan["u_val"] = target_url
                    post_pct_map = {'emoji': post_emoji_percentage, 'hashtag': post_hashtag_percentage}
                    post_emoji_instruction, post_hashtag_instruction = get_dynamic_instructions(post_pct_map, post_meta_plan, brand_name, target_url, gambling_hashtags)
                    core_content_instruction = "No specific brand/URL/keyword requirements."
                    if post_meta_plan.get("b") == 1 and brand_name:
                        core_content_instruction = f"MENTION REQUIREMENT: You MUST include the brand name '{brand_name}' naturally. Pretend you are playing there or asking a question about it. DO NOT praise it directly."
                    elif post_meta_plan.get("u") == 1 and target_url:
                        core_content_instruction = f"MENTION REQUIREMENT: You MUST include the URL '{target_url}' naturally. Use it as a context setting (e.g., 'I was scrolling {target_url} when...'). DO NOT say 'Visit {target_url} for bonus'."
                    elif post_meta_plan.get("k") and post_meta_plan["k"]:
                        kw = post_meta_plan['k'][0]
                        core_content_instruction = (
                            f"MENTION REQUIREMENT: You MUST include the keyword '{kw}' naturally **AS PART OF A SENTENCE**, "
                            f"such as asking for the file name, or using it as a topic of conversation. "
                            f"**CRITICAL**: Do NOT place the keyword at the very end of the sentence or put quotes around it."
                        )
                    slang_instruction = generate_slang_instruction(lingo_list, malaysian_slang_percentage)

                    strict_exclusion_instruction = "No additional strict exclusions." 
                    context_exclusion_target = "No contextual exclusion is necessary for a new post."

                    system_prompt_for_post = ULTIMATE_SYSTEM_PROMPT.format(
                        context_block="You are writing a new social media post.", 
                        content_type="post", 
                        language=plan_item['language'], 
                        persona=post_meta_plan.get('p', 'a normal person'), 
                        style=post_meta_plan.get('s', 'casual'), 
                        topic_or_intent=plan_item['topic'], 
                        min_words=15, 
                        max_words=35, 
                        core_content_instruction=core_content_instruction, 
                        slang_instruction=slang_instruction, 
                        emoji_instruction=post_emoji_instruction, 
                        hashtag_instruction=post_hashtag_instruction,
                        strict_exclusion_instruction=strict_exclusion_instruction,
                        context_exclusion_target=context_exclusion_target
                    )
                    post_text, post_cost = generate_text_from_ai_claude(anthropic_client, model="claude-sonnet-4-5-20250929", system_prompt=system_prompt_for_post, user_prompt="Go.", max_tokens=150, temperature=0.9)
                    accumulated_cost += post_cost
                    if not post_text: status_text.error(f"主帖 #{global_index + 1} 生成失败，跳过。"); time.sleep(2); continue
                    
                    final_post_text, final_post_m = finalize_text_and_flags(post_text, post_meta_plan, brand_name, all_keywords=selected_project.get('keywords', []), target_url=target_url)
                    post_idem_key = make_idempotency_key(selected_order_item_id, generation_phase_id, global_index, "post")
                    if supa_exists_by_key(supabase, "content", post_idem_key): continue
                    insert_res = supabase.table("content").insert({"order_item_id": selected_order_item_id, "task_type": "post", "content_text": final_post_text, "metadata": final_post_m, "idempotency_key": post_idem_key}).execute()
                    post_db_id = insert_res.data[0]['id']

                    # --- C. 互动内容生成 ---
                    interactions_to_insert = []
                    # C.1 评论生成
                    for j in range(num_comments_per_post):
                        status_text.info(f"💬 正在为主帖 {global_index + 1} 生成评论 {j+1}/{num_comments_per_post}...")
                        
                        # 1. 定义元数据字典 cm_meta
                        interaction_plan = {"language": plan_item['language'], "style": weighted_sample(style_pct), "persona": weighted_sample(persona_pct) if "Comment" in persona_scope else None}
                        cm_meta = {"l": final_post_m.get("l", "EN"), "p": interaction_plan["persona"], "s": interaction_plan["style"], "it": weighted_sample(it_pct), "k": maybe_one_keyword(comment_keyword_percentage, st.session_state.kw_pick_comment)}
                        
                        cm_meta["b"] = 0; cm_meta["u"] = 0
                        if cm_meta["u"] == 1: cm_meta["u_val"] = target_url
                        
                        comment_pct_map = {'emoji': comment_emoji_percentage, 'hashtag': comment_hashtag_percentage}
                        comment_emoji_instruction, comment_hashtag_instruction = get_dynamic_instructions(comment_pct_map, cm_meta, brand_name, target_url, gambling_hashtags)
                        
                        # 2. 定义核心指令
                        core_content_instruction_comment = "You MUST NOT include the brand name or URL in your reply. Do NOT mention any specific keywords."

                        # ❗ 修正：添加缺失的 strict_exclusion_instruction 定义 (解决 KeyError)
                        if cm_meta.get("b") == 1 or cm_meta.get("u") == 1:
                            # 理论上 Comment 0% 包含率，不会走到这里
                            strict_exclusion_instruction = "You are REQUIRED to mention the Brand/URL/Keyword (as instructed in 6)."
                        else:
                            # Comment 100% 走这里
                            strict_exclusion_instruction = "You MUST NOT mention the Brand Name or URL under any circumstances in your content."
                            
                        slang_instruction_comment = generate_slang_instruction(lingo_list, malaysian_slang_percentage)
                        
                        # 3. 定义主题 (使用 Comment 的语言和主题)
                        interaction_intent = random.choice(INTERACTION_INTENT_POOL if plan_item['language'] == 'English' else INTERACTION_INTENT_POOL_MS)
                        combined_intent = f"The main topic of the post you are replying to is: '{plan_item['topic']}'. Your task is to apply the interaction intent: '{interaction_intent}' specifically to this topic."

                        # 1. 检查是否需要排除 Brand/URL
                        should_exclude = not (cm_meta.get("b") == 1 or cm_meta.get("u") == 1)

                        if should_exclude and brand_name:
                            # 如果 Brand 或 URL 存在于 post_text 中，就强制排除
                            context_exclusion_target = f"You MUST treat '{brand_name}' and '{target_url}' as forbidden words and names. Do NOT mention them, even if the parent post contains them."
                        else:
                            context_exclusion_target = "No additional contextual exclusion needed."

                        # 4. 生成内容
                        system_prompt_for_comment = ULTIMATE_SYSTEM_PROMPT.format(
                            context_block=f'You are replying to this post: "{final_post_text}"', 
                            content_type="comment", 
                            language=plan_item['language'], 
                            persona=cm_meta.get('p', 'a normal person'), 
                            style=cm_meta.get('s', 'casual'), 
                            topic_or_intent=combined_intent, 
                            min_words=5, max_words=25, 
                            core_content_instruction=core_content_instruction_comment, 
                            slang_instruction=slang_instruction_comment, 
                            emoji_instruction=comment_emoji_instruction, 
                            hashtag_instruction=comment_hashtag_instruction,
                            # ❗ 修正：添加缺失的参数
                            strict_exclusion_instruction=strict_exclusion_instruction,
                            context_exclusion_target=context_exclusion_target 
                        )
                        comment_text, comment_cost = generate_text_from_ai_claude(anthropic_client, model="claude-sonnet-4-5-20250929", system_prompt=system_prompt_for_comment, user_prompt="Go.", max_tokens=80, temperature=0.95)
                        accumulated_cost += comment_cost
                        
                        if comment_text:
                            ctext, final_cm_meta = finalize_text_and_flags(comment_text, cm_meta, brand_name, all_keywords=selected_project.get('keywords', []), target_url=target_url)
                            interactions_to_insert.append({"order_item_id": selected_order_item_id, "task_type": "comment", "content_text": ctext, "parent_content_id": post_db_id, "metadata": final_cm_meta, "idempotency_key": make_idempotency_key(selected_order_item_id, generation_phase_id, global_index, "comment", j)})
                    # C.2 引用生成
                    for j in range(num_quotes_per_post):
                        status_text.info(f"✍️ 正在为主帖 {global_index + 1} 生成引用 {j+1}/{num_quotes_per_post}...")
                        
                        # 1. 定义元数据字典 qt_meta
                        interaction_plan = {"language": plan_item['language'], "style": weighted_sample(style_pct), "persona": weighted_sample(persona_pct) if "Quote" in persona_scope else None}
                        qt_meta = {"l": final_post_m.get("l", "EN"), "p": interaction_plan["persona"], "s": interaction_plan["style"], "it": weighted_sample(it_pct), "k": maybe_one_keyword(quote_keyword_percentage, st.session_state.kw_pick_quote)}
                        
                        ub, uu = pick_brand_or_url(quote_brand_percentage, quote_url_percentage, bool(target_url)); qt_meta["b"] = 1 if ub else 0; qt_meta["u"] = 1 if uu else 0
                        if qt_meta["u"] == 1: qt_meta["u_val"] = target_url
                        
                        quote_pct_map = {'emoji': quote_emoji_percentage, 'hashtag': quote_hashtag_percentage}
                        quote_emoji_instruction, quote_hashtag_instruction = get_dynamic_instructions(quote_pct_map, qt_meta, brand_name, target_url, gambling_hashtags)
                        
                        # 2. 定义核心指令
                        core_content_instruction_quote = "You MUST NOT include the brand name or URL in your reply. Do NOT mention any specific keywords."                       
                        if qt_meta.get("b") == 1 and brand_name:
                            core_content_instruction_quote = f"You MUST mention '{brand_name}' in your quote opinion. Keep it neutral or curious."
                        elif qt_meta.get("u") == 1 and target_url:
                            core_content_instruction_quote = f"You MUST mention '{target_url}' naturally (e.g., 'Saw similar stuff on {target_url}')."
                        elif qt_meta.get("k") and qt_meta["k"]:
                            kw = qt_meta['k'][0]
                            core_content_instruction_quote = (
                                f"You MUST naturally integrate the keyword '{kw}' into a sentence. "
                                f"**CRITICAL**: Do NOT let the keyword be the last word in your reply."
                            )
                            
                        slang_instruction_quote = generate_slang_instruction(lingo_list, malaysian_slang_percentage)
                        
                        # 3. 定义主题 (使用 Quote 的语言和主题)
                        interaction_intent = random.choice(INTERACTION_INTENT_POOL if plan_item['language'] == 'English' else INTERACTION_INTENT_POOL_MS)
                        combined_intent = f"The main topic of the post you are quoting is: '{plan_item['topic']}'. Your task is to apply the interaction intent: '{interaction_intent}' specifically to this topic."
                        
                        if qt_meta.get("b") == 1 or qt_meta.get("u") == 1:
                            strict_exclusion_instruction = "You are REQUIRED to mention the Brand/URL/Keyword (as instructed in 6)."
                        else:
                            strict_exclusion_instruction = "You MUST NOT mention the Brand Name or URL under any circumstances in your content."

                        # 1. 检查是否需要排除 Brand/URL
                        should_exclude = not (qt_meta.get("b") == 1 or qt_meta.get("u") == 1)

                        if should_exclude and brand_name:
                            # 如果 Brand 或 URL 存在于 post_text 中，就强制排除
                            context_exclusion_target = f"You MUST treat '{brand_name}' and '{target_url}' as forbidden words and names. Do NOT mention them, even if the parent post contains them."
                        else:
                            context_exclusion_target = "No additional contextual exclusion needed."

                        # 4. 生成内容
                        system_prompt_for_quote = ULTIMATE_SYSTEM_PROMPT.format(
                            context_block=f'You are quoting this post: "{final_post_text}"', 
                            content_type="quote", 
                            language=plan_item['language'], 
                            persona=qt_meta.get('p', 'a normal person'), 
                            style=qt_meta.get('s', 'casual'), 
                            topic_or_intent=combined_intent, 
                            min_words=10, max_words=30, 
                            core_content_instruction=core_content_instruction_quote, 
                            slang_instruction=slang_instruction_quote, 
                            emoji_instruction=quote_emoji_instruction, 
                            hashtag_instruction=quote_hashtag_instruction,
                            # ❗ 修正：添加缺失的参数
                            strict_exclusion_instruction=strict_exclusion_instruction,
                            context_exclusion_target=context_exclusion_target 
                        )
                        quote_text, quote_cost = generate_text_from_ai_claude(anthropic_client, model="claude-sonnet-4-5-20250929", system_prompt=system_prompt_for_quote, user_prompt="Go.", max_tokens=100, temperature=0.9)
                        accumulated_cost += quote_cost
                        
                        if quote_text:
                            qtext, final_qt_meta = finalize_text_and_flags(quote_text, qt_meta, brand_name, all_keywords=selected_project.get('keywords', []), target_url=target_url)
                            interactions_to_insert.append({"order_item_id": selected_order_item_id, "task_type": "quote", "content_text": qtext, "parent_content_id": post_db_id, "metadata": final_qt_meta, "idempotency_key": make_idempotency_key(selected_order_item_id, generation_phase_id, global_index, "quote", j)})

                    # --- D. 互动内容批量入库 ---
                    if interactions_to_insert:
                        status_text.info(f"💾 正在为主帖 {global_index + 1} 保存 {len(interactions_to_insert)} 条互动...")
                        supabase.table("content").insert(interactions_to_insert).execute()
                
                    # --- E. Repost 占位符创建 (已整合) ---
                    if num_retweets_per_post > 0:
                        retweets_to_insert = []
                        status_text.info(f"➕ 正在为主帖 {global_index + 1} 创建 {num_retweets_per_post} 个 Retweet 占位符...")
                        for k in range(num_retweets_per_post):
                            retweet_entry = {"order_item_id": selected_order_item_id, "task_type": "retweet", "content_text": None, "parent_content_id": post_db_id, "metadata": None, "idempotency_key": None}
                            retweets_to_insert.append(retweet_entry)
                        if retweets_to_insert:
                            supabase.table("content").insert(retweets_to_insert).execute()

                except Exception as e:
                    st.error(f"处理主帖 #{global_index + 1} 时发生严重错误: {e}")
                    import traceback
                    st.code(traceback.format_exc())
                    time.sleep(5)
                    continue
            
            st.success("✅ 所有缺失的主帖及其互动已生成完毕！")

        # --- 情况二：Post 的数量吻合 (进入“修复”模式) ---
        else:
            status_text.info("主帖数量已满足。正在检查每个主帖的互动完整性...")
            time.sleep(2)
            
            work_was_done_in_fixing = False
            
            for index, post in enumerate(existing_posts):
                # ❗ 修复：定义用于显示的 Post 序号
                display_post_number = index + 1

                post_db_id = post['id']
                final_post_text = post['content_text']
                post_language = "English" if (post.get('metadata', {}).get('l') == 'EN') else "Malay"
                
                # --- 核心修复：同时检查 Comment, Quote, 和 Repost ---
                comments_res = supabase.table("content").select("id", count="exact").eq("parent_content_id", post_db_id).eq("task_type", "comment").execute()
                quotes_res = supabase.table("content").select("id", count="exact").eq("parent_content_id", post_db_id).eq("task_type", "quote").execute()
                reposts_res = supabase.table("content").select("id", count="exact").eq("parent_content_id", post_db_id).eq("task_type", "retweet").execute()
                
                comments_needed = num_comments_per_post - comments_res.count
                quotes_needed = num_quotes_per_post - quotes_res.count
                reposts_needed = num_retweets_per_post - reposts_res.count

                if comments_needed <= 0 and quotes_needed <= 0 and reposts_needed <= 0:
                    continue # 这个主帖是完整的，跳过

                work_was_done_in_fixing = True
                # ❗ 修复：使用 display_post_number
                status_text.warning(f"Post #{display_post_number} (DB ID: {post_db_id}) 缺少互动，开始补全...")
                
                interactions_to_insert = []
                # --- 补全评论 ---
                if comments_needed > 0:
                    for j in range(comments_needed):
                        # ❗ 修复：使用 display_post_number
                        status_text.info(f"💬 正在为 Post #{display_post_number} 补全评论 {j+1}/{comments_needed}...")
                        interaction_plan = {"language": post_language, "style": weighted_sample(style_pct), "persona": weighted_sample(persona_pct) if "Comment" in persona_scope else None}
                        cm_meta = {"l": lang_map.get(post_language, "EN"), "p": interaction_plan["persona"], "s": interaction_plan["style"], "it": weighted_sample(it_pct), "k": maybe_one_keyword(comment_keyword_percentage, st.session_state.kw_pick_comment)}
                        cm_meta["b"] = 0; cm_meta["u"] = 0
                        if cm_meta["u"] == 1: cm_meta["u_val"] = target_url
                        comment_pct_map = {'emoji': comment_emoji_percentage, 'hashtag': comment_hashtag_percentage}
                        comment_emoji_instruction, comment_hashtag_instruction = get_dynamic_instructions(comment_pct_map, cm_meta, brand_name, target_url, gambling_hashtags)
                        core_content_instruction_comment = "You MUST NOT include the brand name or URL in your reply. Do NOT mention any specific keywords."

                        # ❗ 修正：添加缺失的 strict_exclusion_instruction 定义 (解决 KeyError)
                        if cm_meta.get("b") == 1 or cm_meta.get("u") == 1:
                            # 理论上 Comment 0% 包含率，不会走到这里
                            strict_exclusion_instruction = "You are REQUIRED to mention the Brand/URL/Keyword (as instructed in 6)."
                        else:
                            # Comment 100% 走这里
                            strict_exclusion_instruction = "You MUST NOT mention the Brand Name or URL under any circumstances in your content."
                            
                        slang_instruction_comment = generate_slang_instruction(lingo_list, malaysian_slang_percentage)
                        
                        # 修正：使用 post_language
                        interaction_intent = random.choice(INTERACTION_INTENT_POOL if post_language == 'English' else INTERACTION_INTENT_POOL_MS)
                        
                        # 修正：使用 final_post_text 作为主题上下文
                        combined_intent = f"The post you are replying to is: '{final_post_text}'. Your task is to apply the interaction intent: '{interaction_intent}' specifically to this content."                    

                        # 1. 检查是否需要排除 Brand/URL
                        should_exclude = not (cm_meta.get("b") == 1 or cm_meta.get("u") == 1) # 或者 qt_meta

                        if should_exclude and brand_name:
                            # 如果 Brand 或 URL 存在于 post_text 中，就强制排除
                            context_exclusion_target = f"You MUST treat '{brand_name}' and '{target_url}' as forbidden words and names. Do NOT mention them, even if the parent post contains them."
                        else:
                            context_exclusion_target = "No additional contextual exclusion needed."

                        system_prompt_for_comment = ULTIMATE_SYSTEM_PROMPT.format(
                            context_block=f'You are replying to this post: "{final_post_text}"', 
                            content_type="comment", 
                            language=post_language, 
                            persona=cm_meta.get('p', 'a normal person'), 
                            style=cm_meta.get('s', 'casual'), 
                            topic_or_intent=combined_intent, 
                            min_words=5, max_words=25, 
                            core_content_instruction=core_content_instruction_comment, 
                            slang_instruction=slang_instruction_comment, 
                            emoji_instruction=comment_emoji_instruction, 
                            hashtag_instruction=comment_hashtag_instruction,
                            # ❗ 修正：添加缺失的参数
                            strict_exclusion_instruction=strict_exclusion_instruction,
                            context_exclusion_target=context_exclusion_target 
                        )
                        comment_text, comment_cost = generate_text_from_ai_claude(anthropic_client, model="claude-sonnet-4-5-20250929", system_prompt=system_prompt_for_comment, user_prompt="Go.", max_tokens=80, temperature=0.95)
                        accumulated_cost += comment_cost
                        if comment_text:
                            ctext, final_cm_meta = finalize_text_and_flags(comment_text, cm_meta, brand_name,all_keywords=selected_project.get('keywords', []),target_url=target_url)
                            interactions_to_insert.append({"order_item_id": selected_order_item_id, "task_type": "comment", "content_text": ctext, "parent_content_id": post_db_id, "metadata": final_cm_meta, "idempotency_key": make_idempotency_key(selected_order_item_id, generation_phase_id, post_db_id, "comment_fix", j)})
                # --- 补全引用 ---
                if quotes_needed > 0:
                    for j in range(num_quotes_per_post):
                        # ❗ 修复：使用 display_post_number
                        status_text.info(f"✍️ 正在为主帖 #{display_post_number} 生成引用 {j+1}/{num_quotes_per_post}...")
                        
                        interaction_plan = {"language": post_language, "style": weighted_sample(style_pct), "persona": weighted_sample(persona_pct) if "Quote" in persona_scope else None}
                        qt_meta = {"l": lang_map.get(post_language, "EN"), "p": interaction_plan["persona"], "s": interaction_plan["style"], "it": weighted_sample(it_pct), "k": maybe_one_keyword(quote_keyword_percentage, st.session_state.kw_pick_quote)}
                        
                        ub, uu = pick_brand_or_url(quote_brand_percentage, quote_url_percentage, bool(target_url)); qt_meta["b"] = 1 if ub else 0; qt_meta["u"] = 1 if uu else 0
                        if qt_meta["u"] == 1: qt_meta["u_val"] = target_url
                        quote_pct_map = {'emoji': quote_emoji_percentage, 'hashtag': quote_hashtag_percentage}
                        quote_emoji_instruction, quote_hashtag_instruction = get_dynamic_instructions(quote_pct_map, qt_meta, brand_name, target_url, gambling_hashtags)
                        core_content_instruction_quote = "No specific brand/URL/keyword to include."
                        if qt_meta.get("b") == 1 and brand_name: core_content_instruction_quote = f"You MUST naturally integrate the term '{brand_name}' into a sentence."
                        elif qt_meta.get("u") == 1 and target_url: core_content_instruction_quote = f"You MUST naturally integrate the URL '{target_url}' into a sentence."
                        elif qt_meta.get("k") and qt_meta["k"]:
                            kw = qt_meta['k'][0]
                            core_content_instruction_quote = (
                                f"You MUST naturally integrate the keyword '{kw}' into a sentence. "
                                f"**CRITICAL**: Do NOT let the keyword be the last word in your reply."
                            )
                        slang_instruction_quote = generate_slang_instruction(lingo_list, malaysian_slang_percentage)
                        
                        # 修正：使用 post_language
                        interaction_intent = random.choice(INTERACTION_INTENT_POOL if post_language == 'English' else INTERACTION_INTENT_POOL_MS)
                        
                        # 修正：使用 final_post_text 作为主题上下文
                        combined_intent = f"The post you are quoting is: '{final_post_text}'. Your task is to apply the interaction intent: '{interaction_intent}' specifically to this content."
                        
                        if qt_meta.get("b") == 1 or qt_meta.get("u") == 1:
                            strict_exclusion_instruction = "You are REQUIRED to mention the Brand/URL/Keyword (as instructed in 6)."
                        else:
                            strict_exclusion_instruction = "You MUST NOT mention the Brand Name or URL under any circumstances in your content."

                        # 1. 检查是否需要排除 Brand/URL
                        should_exclude = not (qt_meta.get("b") == 1 or qt_meta.get("u") == 1)

                        if should_exclude and brand_name:
                            # 如果 Brand 或 URL 存在于 post_text 中，就强制排除
                            context_exclusion_target = f"You MUST treat '{brand_name}' and '{target_url}' as forbidden words and names. Do NOT mention them, even if the parent post contains them."
                        else:
                            context_exclusion_target = "No additional contextual exclusion needed."    

                        system_prompt_for_quote = ULTIMATE_SYSTEM_PROMPT.format(
                            context_block=f'You are quoting this post: "{final_post_text}"', 
                            content_type="quote", 
                            language=post_language, 
                            persona=qt_meta.get('p', 'a normal person'), 
                            style=qt_meta.get('s', 'casual'), 
                            topic_or_intent=combined_intent, 
                            min_words=10, max_words=30, 
                            core_content_instruction=core_content_instruction_quote, 
                            slang_instruction=slang_instruction_quote, 
                            emoji_instruction=quote_emoji_instruction, 
                            hashtag_instruction=quote_hashtag_instruction,
                            # ❗ 修正：添加缺失的参数
                            strict_exclusion_instruction=strict_exclusion_instruction,
                            context_exclusion_target=context_exclusion_target 
                        )
                        quote_text, quote_cost = generate_text_from_ai_claude(anthropic_client, model="claude-sonnet-4-5-20250929", system_prompt=system_prompt_for_quote, user_prompt="Go.", max_tokens=100, temperature=0.9)
                        accumulated_cost += quote_cost
                        if quote_text:
                            qtext, final_qt_meta = finalize_text_and_flags(quote_text, qt_meta, brand_name, all_keywords=selected_project.get('keywords', []), target_url=target_url)
                            interactions_to_insert.append({"order_item_id": selected_order_item_id, "task_type": "quote", "content_text": qtext, "parent_content_id": post_db_id, "metadata": final_qt_meta, "idempotency_key": make_idempotency_key(selected_order_item_id, generation_phase_id, post_db_id, "quote_fix", j)})

                # --- 核心修复：补全 Repost 占位符 ---
                if reposts_needed > 0:
                    # ❗ 修复：使用 display_post_number
                    status_text.info(f"➕ 正在为 Post #{display_post_number} 补全 {reposts_needed} 个 Retweet 占位符...")
                    for k in range(reposts_needed):
                        retweet_entry = {"order_item_id": selected_order_item_id, "task_type": "retweet", "content_text": None, "parent_content_id": post_db_id, "metadata": None, "idempotency_key": None}
                        interactions_to_insert.append(retweet_entry)

                if interactions_to_insert:
                    status_text.info(f"💾 正在为 Post #{post_db_id} 保存 {len(interactions_to_insert)} 条补全的互动...")
                    supabase.table("content").insert(interactions_to_insert).execute()

            if work_was_done_in_fixing:
                st.success("✅ 所有缺失的互动已补全！")
            else:
                st.success("✅ 任务已是最新状态，所有主帖和互动都已完整，无需任何操作。")

        # --- 统一的收尾工作 ---
        progress_bar.progress(1.0, text="全部完成！")
        status_text.empty()
        
        if accumulated_cost > 0:
            st.info("内容生成/补全完毕。正在更新数据库中的总成本...")
            try:
                cost_res = supabase.table("order_items").select("cost").eq("id", selected_order_item_id).single().execute()
                current_cost = float(cost_res.data.get('cost') or 0.0) if cost_res.data else 0.0
                new_total_cost = current_cost + accumulated_cost
                update_response = supabase.table("order_items").update({"cost": new_total_cost}).eq("id", selected_order_item_id).execute()

                if not update_response.data:
                     st.error("❌ 数据库成本更新失败！请检查RLS策略。")
                     raise Exception("Supabase update returned no data.")

                st.success(f"**任务 ID {selected_order_item_id} 成本更新成功！**\n- **本次运行花费:** `${accumulated_cost:.6f}`\n- **数据库中新的总花费:** `${new_total_cost:.6f}`")
                st.balloons()

            except Exception as e:
                st.error(f"❌ 更新最终成本时发生严重错误: {e}")
                st.warning(f"请手动为任务 ID {selected_order_item_id} 加上本次运行的花费: ${accumulated_cost:.6f}")
        else:
            st.info("本次运行没有产生费用，因为所有内容都已是最新状态或仅补充了Repost。")
        
        st.success("🎉 操作执行完毕！")

    if 'generated_content' in st.session_state:
        del st.session_state['generated_content']

# st.divider()

# # --- 4. 最终结果提示 ---
# st.header("3. Generation Result")
# st.info("The generation process now saves content directly to the database. "
#         "After running the campaign, you can view the results in your Supabase table "
#         "or on another page designed for content review.")

# if st.query_params.get("status") == "success":
#     st.success("🎉 All content has been successfully saved!"); st.balloons(); st.query_params.clear()

# # ==============================================================================
# # --- 实时预览面板 ---
# # ==============================================================================
# st.divider()
# st.header("🔎 Live Preview: Latest Content from Database")

# try:
#     current_task_id = selected_order_item_id if 'selected_order_item_id' in locals() else None
#     if current_task_id:
#         st.caption(f"Showing content for selected Task ID: `{current_task_id}`")
#         preview_res = supabase.table("content").select("*").eq("order_item_id", current_task_id).order("id", desc=True).limit(200).execute()
#     else:
#         st.caption("No task selected. Falling back to show the 50 most recent entries in the database.")
#         preview_res = supabase.table("content").select("*").order("id", desc=True).limit(50).execute()
#     rows = preview_res.data or []
# except Exception as e:
#     rows = []
#     st.error(f"❌ Failed to fetch preview data from database: {e}")

# if not rows:
#     st.info("No content found in the database based on the current filter.")
# else:
#     st.caption(f"Displaying {len(rows)} most recent entries.")
#     import pandas as pd
#     df = pd.DataFrame(rows)
#     display_cols = ['id', 'task_type', 'order_item_id', 'parent_content_id', 'content_text', 'created_at', 'metadata']
#     existing_cols = [col for col in display_cols if col in df.columns]
#     st.dataframe(df[existing_cols])
#     with st.expander("Show simple list view"):
#         for r in rows:
#             st.markdown(f"- **ID: `{r.get('id')}`** | Type: `{r.get('task_type')}` | Task: `{r.get('order_item_id')}` | Parent: `{r.get('parent_content_id')}`\n  - **Content**: {str(r.get('content_text') or '')[:120]}...")
