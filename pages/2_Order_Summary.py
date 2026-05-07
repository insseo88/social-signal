# pages/2_Order_Summary.py (已修正 LinkColumn 参数)

import streamlit as st
from supabase import create_client, Client
import pandas as pd

# --- 检查登录状态 ---
# 如果用户未登录，则无法访问此页面
if 'user' not in st.session_state or st.session_state.user is None:
    st.warning("⚠️ 请先在主页登录才能访问此页面。")
    st.page_link("app.py", label="返回主页登录", icon="🏠")
    st.stop()

# --- 页面配置 ---
st.set_page_config(page_title="✅ 任务仪表盘", layout="wide")

# --- Supabase 初始化 ---
@st.cache_resource
def get_supabase_client(url: str, key: str) -> Client:
    return create_client(url, key)

def init_supabase_client():
    try:
        supabase_url = st.secrets["supabase_url"]
        supabase_key = st.secrets["supabase_key"]
        return get_supabase_client(supabase_url, supabase_key)
    except Exception:
        return None

supabase = init_supabase_client()

# --- 数据获取函数 ---
@st.cache_data(ttl=60)
def get_all_tasks():
    """
    获取所有独立的任务项 (order_items)，并关联其父订单和类型信息。
    """
    if not supabase: return []
    try:
        response = supabase.table("order_items_with_status").select(
            "*, orders!inner(*, platform_type(platform_type)), post_type(post_type)"
        ).order("id", desc=True).execute()
        return response.data if response.data else []
    except Exception as e:
        st.error(f"获取任务数据时出错: {e}")
        return []

# --- 页面标题 ---
st.title("✅ 任务仪表盘")
st.markdown("在这里，您可以清晰地追踪每一个独立任务的进度。")

if not supabase:
    st.error("❌ 无法连接到 Supabase。请检查配置。")
    st.stop()

# --- 1. 数据加载与准备 ---
all_tasks = get_all_tasks()

if not all_tasks:
    st.info("目前还没有任何任务。")
    st.stop()

platform_options = sorted(list(set(t['orders']['platform_type']['platform_type'] for t in all_tasks if t.get('orders'))))
brand_options = sorted(list(set(t['orders']['target_brand'] for t in all_tasks if t.get('orders'))))
status_options = sorted(list(set(
    t.get('status') for t in all_tasks if t.get('status') is not None
)))

# --- 2. 筛选栏 ---
st.subheader("🔍 筛选任务")
filter_cols = st.columns([2, 2, 2, 1])

with filter_cols[0]:
    selected_brands = st.multiselect("品牌 (Brand)", options=["All"] + brand_options, default="All")
with filter_cols[1]:
    selected_platforms = st.multiselect("平台 (Platform)", options=["All"] + platform_options, default="All")
with filter_cols[2]:
    selected_statuses = st.multiselect("状态 (Status)", options=["All"] + status_options, default="All")
with filter_cols[3]:
    st.write("")
    st.write("")
    if st.button("🔄 刷新数据", width='stretch'):
        st.cache_data.clear()
        st.rerun()

# --- 3. 数据筛选逻辑 ---
filtered_tasks = all_tasks
if "All" not in selected_brands:
    filtered_tasks = [t for t in filtered_tasks if t.get('orders') and t['orders']['target_brand'] in selected_brands]
if "All" not in selected_platforms:
    filtered_tasks = [t for t in filtered_tasks if t.get('orders') and t['orders']['platform_type']['platform_type'] in selected_platforms]
if "All" not in selected_statuses:
    filtered_tasks = [t for t in filtered_tasks if t['status'] in selected_statuses]

st.divider()

# --- 4. 任务列表展示 ---
st.subheader(f"显示 {len(filtered_tasks)} 个任务")

if not filtered_tasks:
    st.warning("没有找到符合筛选条件的任务。")
else:
    display_data = []
    for task in filtered_tasks:
        # Safely get nested dictionary information
        order_info = task.get('orders', {})
        platform_info = order_info.get('platform_type', {})
        post_type_info = task.get('post_type', {})
        
        display_data.append({
            # Use .get() for all potentially missing keys from the main 'task' object
            "Task ID": task.get('id', 'N/A'),
            "Status": task.get('status', 'N/A'), # --- FIX APPLIED HERE ---
            "Post Quantity": task.get('post_quantity', 0),

            # These were already safe because 'order_info' is a safe dictionary
            "Target Brand": order_info.get('target_brand', 'N/A'),
            "Target URL": order_info.get('target_url', 'N/A'),
            
            # These are also safe
            "Platform": platform_info.get('platform_type', 'N/A'),
            "Post Type": post_type_info.get('post_type', 'N/A'),
            
            # Keep the original task object for details if needed
            "_details": task 
        })
    
    df_display = pd.DataFrame(display_data)

    st.dataframe(
        df_display,
        column_config={
            "Task ID": st.column_config.NumberColumn("Task ID", format="%d"),
            "Status": st.column_config.TextColumn("Status", help="✅ DONE or 📝 PENDING"),
            "Target Brand": "Brand",
            "Platform": "Platform",
            "Post Type": "Post Type",
            "Post Quantity": st.column_config.NumberColumn("Posts", help="需要生成的帖子数量"),
            # --- 这是被修正的一行 ---
            "Target URL": st.column_config.LinkColumn("URL", display_text="Link"),
            "_details": None, 
        },
        width='stretch',
        hide_index=True,
    )
