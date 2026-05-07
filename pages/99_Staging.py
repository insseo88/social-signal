# pages/99_Staging.py

import streamlit as st
import openai
import anthropic
import time
import json

# ==============================================================================
# --- 安全检查和客户端初始化 ---
# ==============================================================================

st.set_page_config(layout="wide")

# 在这个独立的测试页面里，我们自己初始化所有东西
@st.cache_resource
def init_test_clients():
    """一个专门用于此测试页面的独立客户端初始化函数"""
    # Anthropic Client
    try:
        anthropic_client = anthropic.Anthropic(
            api_key=st.secrets["anthropic_api_key"],
            default_headers={"anthropic-version": "2023-06-01"}
        )
    except Exception as e:
        st.error(f"Anthropic 客户端初始化失败: {e}")
        anthropic_client = None

    # OpenAI Client
    try:
        openai.api_key = st.secrets["openai_api_key"]
        openai_ready = True
    except Exception as e:
        st.error(f"OpenAI API 密钥设置失败: {e}")
        openai_ready = False
        
    if not anthropic_client or not openai_ready:
        st.warning("至少有一个 AI 客户端未能成功初始化。请检查您的 secrets.toml 文件。")

    return anthropic_client, openai_ready

anthropic_client, openai_ready = init_test_clients()


# ==============================================================================
# --- AI 调用函数 (这个页面专属) ---
# ==============================================================================

# 我们把两个 AI 的调用函数都放在这里，让这个页面完全自给自足

def call_with_retry(fn, max_retries=3, base_delay=1.0):
    """简化的重试函数"""
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if attempt == max_retries - 1:
                st.error(f"API 调用在 {max_retries} 次尝试后最终失败: {e}")
                raise
            time.sleep(base_delay * (2 ** attempt))

def get_token_cost(model_name: str, prompt_tokens: int, completion_tokens: int, pricing_dict: dict) -> float:
    """简化的成本计算函数"""
    pricing = pricing_dict.get(model_name)
    if not pricing: return 0.0
    return (prompt_tokens * pricing["input"]) + (completion_tokens * pricing["output"])

def generate_openai(model, system_prompt, user_prompt, temperature, max_tokens, pricing_dict):
    if not openai_ready: return "OpenAI 客户端未就绪", 0, 0, 0
    try:
        response = call_with_retry(lambda: openai.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=temperature,
            max_tokens=max_tokens
        ))
        content = response.choices[0].message.content
        in_tokens = response.usage.prompt_tokens
        out_tokens = response.usage.completion_tokens
        cost = get_token_cost(model, in_tokens, out_tokens, pricing_dict)
        return content, cost, in_tokens, out_tokens
    except Exception as e:
        return f"错误: {e}", 0, 0, 0

def generate_claude(model, system_prompt, user_prompt, temperature, max_tokens, pricing_dict):
    if not anthropic_client: return "Anthropic 客户端未就绪", 0, 0, 0
    try:
        response = call_with_retry(lambda: anthropic_client.messages.create(
            model=model,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=temperature,
            max_tokens=max_tokens
        ))
        content = response.content[0].text
        in_tokens = response.usage.input_tokens
        out_tokens = response.usage.output_tokens
        cost = get_token_cost(model, in_tokens, out_tokens, pricing_dict)
        return content, cost, in_tokens, out_tokens
    except Exception as e:
        return f"错误: {e}", 0, 0, 0

# ==============================================================================
# --- 页面主体 ---
# ==============================================================================

st.title("🔬 模型竞技场 (Staging)")
st.markdown("一个用于**并行测试** OpenAI 和 Anthropic 模型输出的简单、安全的环境。")
st.info("**这里的任何操作都不会写入数据库**，所有结果在刷新页面后都会消失。")

# --- 1. 共享的 Prompt 和参数 ---
st.header("1. 统一的 Prompt 和参数")

# 使用 Expander 来保持界面整洁
with st.expander("点击展开/折叠 Prompt 和参数设置", expanded=True):
    # Prompt 模板
    ULTIMATE_SYSTEM_PROMPT = st.text_area(
        "系统 Prompt (System Prompt)",
        value="""You are a creative Malaysian netizen. Your primary goal is to write content that sounds **authentically Malaysian**.
---
**CONTEXT:** {context_block}
---
**YOUR TASK & STRICT RULES:**
1.  Write ONE piece of content: A `{content_type}`.
2.  Language: You MUST write in `{language}`.
3.  Character: Your persona is '{persona}' with a '{style}' vibe.
4.  Topic/Intent: Your writing must be about: "{topic_or_intent}".
5.  Length: Your reply MUST be between **{min_words} and {max_words} words**.
6.  Final Output Format: You MUST output ONLY the final text.
""",
        height=300
    )
    
    # 动态填充的变量
    st.write("---")
    st.subheader("Prompt 变量")
    cols = st.columns(3)
    context_block = cols[0].text_input("Context Block", "Replying to a post about winning.")
    content_type = cols[1].text_input("Content Type", "comment")
    language = cols[2].selectbox("Language", ["English", "Malay"])
    persona = cols[0].text_input("Persona", "The Hopeful Dreamer")
    style = cols[1].text_input("Style", "Excited")
    topic_or_intent = cols[2].text_input("Topic/Intent", "Share a personal story of a small win.")
    min_words = cols[0].number_input("Min Words", 5)
    max_words = cols[1].number_input("Max Words", 25)

    # 通用生成参数
    st.write("---")
    st.subheader("通用生成参数")
    cols = st.columns(2)
    temperature = cols[0].slider("Temperature (随机性)", 0.0, 1.0, 0.7, 0.05)
    max_tokens_out = cols[1].slider("Max Output Tokens (最大输出长度)", 50, 1000, 150)


# --- 2. 模型选择和执行 ---
st.header("2. 模型选择与执行")
col1, col2 = st.columns(2)
with col1:
    openai_model_to_test = st.selectbox("选择 OpenAI 模型", ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"], key="openai_model")
with col2:
    claude_model_to_test = st.selectbox("选择 Claude 模型", ["claude-opus-4-1-20250805", "claude-sonnet-4-5-20250929", "claude-haiku-4-5-20251001"], key="claude_model")

# 简单的定价表，只为这个页面服务
PRICING_TABLE = {
    "gpt-4o": {"input": 5.00 / 1000000, "output": 15.00 / 1000000},
    "gpt-4-turbo": {"input": 10.00 / 1000000, "output": 30.00 / 1000000},
    "gpt-3.5-turbo": {"input": 0.50 / 1000000, "output": 1.50 / 1000000},
    "claude-opus-4-1-20250805": {"input": 15.00 / 1000000, "output": 75.00 / 1000000},
    "claude-sonnet-4-5-20250929": {"input": 3.00 / 1000000, "output": 15.00 / 1000000},
    "claude-haiku-4-5-20251001": {"input": 1.00 / 1000000, "output": 5.00 / 1000000},
}

if st.button("🚀 同时运行两个模型进行对比", type="primary", width='stretch'):
    # 准备最终的 Prompt
    try:
        final_system_prompt = ULTIMATE_SYSTEM_PROMPT.format(
            context_block=context_block,
            content_type=content_type,
            language=language,
            persona=persona,
            style=style,
            topic_or_intent=topic_or_intent,
            min_words=min_words,
            max_words=max_words,
            # 为了简化，这里硬编码一些值
            core_content_instruction="Ensure the content is engaging.",
            slang_instruction="Use local slang if appropriate.",
            emoji_instruction="Add 1-2 emojis.",
            hashtag_instruction="No hashtags needed."
        )
    except KeyError as e:
        st.error(f"填充 Prompt 模板时出错：找不到变量 {e}。")
        st.stop()

    # 使用 st.columns 来实现并行视觉效果
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader(f"🤖 OpenAI ({openai_model_to_test})")
        with st.spinner("正在调用 OpenAI..."):
            o_content, o_cost, o_in, o_out = generate_openai(openai_model_to_test, final_system_prompt, "Go.", temperature, max_tokens_out, PRICING_TABLE)
        st.info(f"**成本:** `${o_cost:.6f}` | **Input:** {o_in} | **Output:** {o_out}")
        st.text_area("生成内容", value=o_content, height=300, key="openai_result")

    with col2:
        st.subheader(f"🧑‍🎨 Claude ({claude_model_to_test})")
        with st.spinner("正在调用 Anthropic..."):
            c_content, c_cost, c_in, c_out = generate_claude(claude_model_to_test, final_system_prompt, "Go.", temperature, max_tokens_out, PRICING_TABLE)
        st.info(f"**成本:** `${c_cost:.6f}` | **Input:** {c_in} | **Output:** {c_out}")
        st.text_area("生成内容", value=c_content, height=300, key="claude_result")

