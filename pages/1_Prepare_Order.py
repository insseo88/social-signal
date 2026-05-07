# pages/1_Prepare_Order.py

import streamlit as st
import datetime
from supabase import create_client, Client
import uuid

# --- 页面配置 ---
st.set_page_config(page_title="📝 准备订单", layout="wide")

# --- 检查登录状态 ---
# 如果用户未登录，则无法访问此页面
if 'user' not in st.session_state or st.session_state.user is None:
    st.warning("⚠️ 请先在主页登录才能访问此页面。")
    st.page_link("app.py", label="返回主页登录", icon="🏠")
    st.stop()

# --- Supabase 初始化 ---
@st.cache_resource
def get_supabase_client(url: str, key: str) -> Client:
    return create_client(url, key)

def init_supabase_client():
    try:
        supabase_url = st.secrets["supabase_url"]
        supabase_key = st.secrets["supabase_key"]
        return get_supabase_client(supabase_url, supabase_key)
    except Exception as e:
        st.error(f"❌ 无法连接到 Supabase。请检查 secrets.toml 文件。详细错误: {e}")
        return None

supabase = init_supabase_client()

# --- 成功消息处理 ---
if 'show_success' in st.session_state and st.session_state.show_success:
    st.success("🎉 所有订单已成功创建!")
    st.balloons()
    del st.session_state.show_success

# --- 数据获取函数 ---
@st.cache_data(ttl=600)
def get_supabase_data(table_name: str, columns: str) -> list:
    if not supabase: return []
    try:
        response = supabase.table(table_name).select(columns).execute()
        return response.data if response.data else []
    except Exception as e:
        st.error(f"无法从 '{table_name}' 表中获取数据: {e}")
        return []

def get_or_create_website_id(url: str):
    """
    检查 URL 是否存在。
    存在 -> 返回 int2 ID。
    不存在 -> 创建 -> 返回新生成的 int2 ID。
    """
    if not url: return None
    
    try:
        # 1. 查找
        response = supabase.table("website_name").select("id").eq("target_url", url).execute()
        if response.data:
            return response.data[0]['id'] # 返回的是数字，例如 1, 2, 55
        
        # 2. 创建 (不用传 ID，数据库会自动生成 1, 2, 3...)
        new_data = {"target_url": url}
        insert_response = supabase.table("website_name").insert(new_data).execute()
        
        if insert_response.data:
            return insert_response.data[0]['id']
            
    except Exception as e:
        st.error(f"处理 Website URL 失败: {e}")
        return None
    return None

# --- 页面标题 ---
st.title("📝 准备订单")
st.markdown("填写订单基本信息，并动态添加所需的任务配置。")

if not supabase:
    st.stop()

# --- 加载数据 ---
platform_data = get_supabase_data("platform_type", "id, platform_type")
post_type_data = get_supabase_data("post_type", "id, post_type")
project_data = get_supabase_data("projects", "id, project_name")

# 创建数据映射
platform_map = {item["platform_type"]: item["id"] for item in platform_data}
post_type_map = {item["post_type"]: item["id"] for item in post_type_data}
project_map = {item["project_name"]: item["id"] for item in project_data}

platform_options = list(platform_map.keys())
post_type_options = list(post_type_map.keys())
# 【优化】项目必选，移除 "None" 选项
project_options = list(project_map.keys()) 

# --- Session State & 动态函数 ---
if 'task_configs' not in st.session_state:
    st.session_state.task_configs = [{"id": str(uuid.uuid4())}]

def add_task_config():
    st.session_state.task_configs.append({"id": str(uuid.uuid4())})

def remove_task_config(config_id: str):
    if len(st.session_state.task_configs) > 1:
        st.session_state.task_configs = [c for c in st.session_state.task_configs if c["id"] != config_id]

# --- 创建表单 ---
with st.form("prepare_order_form", clear_on_submit=True):
    st.subheader("订单基本信息")
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        # 【优化】项目现在是必填项
        selected_project_name = st.selectbox("📂 项目 (Project) *", options=project_options, index=None, placeholder="请选择一个项目")
    with col2:
        target_brand = st.text_input("🏢 目标品牌 *", placeholder="Your Brand")
    with col3:
        target_url = st.text_input("🎯 目标URL *", placeholder="www.example.com")
    with col4:
        start_date = st.date_input("🗓️ 开始日期", datetime.date.today())
    with col5:
        end_date = st.date_input("🗓️ 结束日期", datetime.date.today() + datetime.timedelta(days=7))

    st.divider()
    st.subheader("订单任务配置")

    # --- 动态任务配置UI ---
    for i, config in enumerate(st.session_state.task_configs):
        unique_key_prefix = f"task_{config['id']}"
        with st.container(border=True):
            main_cols = st.columns([2.5, 4, 4])
            with main_cols[0]:
                st.markdown(f"**配置 #{i + 1}**")
                st.selectbox("平台类型", options=platform_options, key=f"{unique_key_prefix}_platform", label_visibility="collapsed")
            with main_cols[1]:
                with st.container(border=True):
                    type_qty_cols = st.columns([2, 1])
                    with type_qty_cols[0]:
                        st.selectbox("📄 帖子类型 1", post_type_options, key=f"{unique_key_prefix}_pt1", index=0 if post_type_options else None)
                    with type_qty_cols[1]:
                        # 【优化】帖子数量可以为0
                        st.number_input("📜 数量", min_value=0, step=1, key=f"{unique_key_prefix}_post_qty1")
                    interaction_cols = st.columns(3)
                    interaction_cols[0].number_input("💬 Comment", min_value=0, step=1, key=f"{unique_key_prefix}_reply1")
                    interaction_cols[1].number_input("🔁 Repost", min_value=0, step=1, key=f"{unique_key_prefix}_retweet1")
                    interaction_cols[2].number_input("✍️ Quote", min_value=0, step=1, key=f"{unique_key_prefix}_quote1")
            with main_cols[2]:
                with st.container(border=True):
                    type_qty_cols_2 = st.columns([2, 1])
                    with type_qty_cols_2[0]:
                        st.selectbox("📄 帖子类型 2", post_type_options, key=f"{unique_key_prefix}_pt2", index=1 if len(post_type_options) > 1 else 0)
                    with type_qty_cols_2[1]:
                        # 【优化】帖子数量可以为0
                        st.number_input("📜 数量", min_value=0, step=1, key=f"{unique_key_prefix}_post_qty2")
                    interaction_cols2 = st.columns(3)
                    interaction_cols2[0].number_input("💬 Comment", min_value=0, step=1, key=f"{unique_key_prefix}_reply2")
                    interaction_cols2[1].number_input("🔁 Repost", min_value=0, step=1, key=f"{unique_key_prefix}_retweet2")
                    interaction_cols2[2].number_input("✍️ Quote", min_value=0, step=1, key=f"{unique_key_prefix}_quote2")

    submit_cols = st.columns([5, 1])
    with submit_cols[1]:
        submitted = st.form_submit_button("✅ 创建订单", type="primary", width='stretch')

# --- 管理按钮 ---
st.subheader("管理任务配置")
manage_cols = st.columns(8)
manage_cols[0].button("➕ 添加", on_click=add_task_config, width='stretch')
if len(st.session_state.task_configs) > 1:
    with manage_cols[1]:
        if st.button("➖ 移除", width='stretch'):
            remove_task_config(st.session_state.task_configs[-1]['id'])
            st.rerun()

# --- 表单提交逻辑 ---
if submitted:
    # 验证输入
    if not selected_project_name or not target_brand or not target_url:
        st.warning("⚠️ 创建失败: 请确保已填写 项目、目标品牌 和 目标URL。")
    else:
        all_items_created = True
        any_task_detected = False
        
        project_id = project_map.get(selected_project_name)
        current_user_id = st.session_state.user.id if st.session_state.user else None

        # --- 获取 Int2 ID ---
        # 这里的 target_url 是用户输入的文本，website_id 是返回的数字 (如 105)
        website_id = get_or_create_website_id(target_url)

        if not website_id:
            st.stop() # 停止运行

        for i, config in enumerate(st.session_state.task_configs):
            unique_key_prefix = f"task_{config['id']}"
            try:
                with st.spinner(f"正在处理配置 #{i + 1}..."):
                    # 检查有效性
                    is_task1_valid = (st.session_state[f"{unique_key_prefix}_post_qty1"] > 0 or 
                                      any(st.session_state[k] > 0 for k in [f"{unique_key_prefix}_reply1", f"{unique_key_prefix}_retweet1", f"{unique_key_prefix}_quote1"]))
                    is_task2_valid = (st.session_state[f"{unique_key_prefix}_post_qty2"] > 0 or 
                                      any(st.session_state[k] > 0 for k in [f"{unique_key_prefix}_reply2", f"{unique_key_prefix}_retweet2", f"{unique_key_prefix}_quote2"]))

                    if not is_task1_valid and not is_task2_valid:
                        continue
                    
                    any_task_detected = True
                    
                    # --- 构建数据 ---
                    order_data = {
                        "project_id": project_id,
                        "target_url": website_id, # 这里存入的是 Int2 数字
                        "target_brand": target_brand,
                        "start_date": str(start_date),
                        "end_date": str(end_date),
                        "platform_type": platform_map[st.session_state[f"{unique_key_prefix}_platform"]],
                        "created_by_user": current_user_id
                    }
                    
                    # 插入 Orders
                    response = supabase.table("orders").insert(order_data).execute()

                    if not response.data:
                        st.error(f"插入订单失败: 配置 #{i + 1}")
                        all_items_created = False; break
                    
                    # 插入 Order Items
                    new_order_id = response.data[0]['id']
                    order_items_to_create = []
                    
                    if is_task1_valid:
                        order_items_to_create.append({ "order_id": new_order_id, "post_type": post_type_map[st.session_state[f"{unique_key_prefix}_pt1"]], "post_quantity": st.session_state[f"{unique_key_prefix}_post_qty1"], "reply_per_post": st.session_state[f"{unique_key_prefix}_reply1"], "retweet_per_post": st.session_state[f"{unique_key_prefix}_retweet1"], "quote_per_post": st.session_state[f"{unique_key_prefix}_quote1"] })
                    if is_task2_valid:
                        order_items_to_create.append({ "order_id": new_order_id, "post_type": post_type_map[st.session_state[f"{unique_key_prefix}_pt2"]], "post_quantity": st.session_state[f"{unique_key_prefix}_post_qty2"], "reply_per_post": st.session_state[f"{unique_key_prefix}_reply2"], "retweet_per_post": st.session_state[f"{unique_key_prefix}_retweet2"], "quote_per_post": st.session_state[f"{unique_key_prefix}_quote2"] })

                    if order_items_to_create:
                        supabase.table("order_items").insert(order_items_to_create).execute()
            
            except Exception as e:
                st.error(f"出错: {e}")
                all_items_created = False; break
        
        if all_items_created and any_task_detected:
            st.session_state.show_success = True
            st.rerun()
        elif not any_task_detected:
            st.warning("无有效任务。")