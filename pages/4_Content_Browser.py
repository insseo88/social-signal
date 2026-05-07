# 【5_Content_Browser.py 的最终完整代码 - 已优化并添加下载功能】

import streamlit as st
from supabase import create_client, Client
import pandas as pd
import datetime
import io # 用于在内存中处理文件

# --- 检查登录状态 ---
# 如果用户未登录，则无法访问此页面
if 'user' not in st.session_state or st.session_state.user is None:
    st.warning("⚠️ 请先在主页登录才能访问此页面。")
    st.page_link("app.py", label="返回主页登录", icon="🏠")
    st.stop()

# --- 页面配置 ---
st.set_page_config(page_title="内容浏览器", layout="wide")
st.title("📖 内容浏览器")
st.caption("在这里浏览、搜索和筛选所有已生成并存入数据库的内容。")

# --- 客户端初始化 (保持不变) ---
@st.cache_resource
def get_supabase_client(url: str, key: str) -> Client:
    return create_client(url, key)

try:
    supabase_url = st.secrets["supabase_url"]
    supabase_key = st.secrets["supabase_key"]
    supabase = get_supabase_client(supabase_url, supabase_key)
except Exception:
    st.error("❌ Supabase 连接失败。请检查你的 secrets.toml 文件。")
    st.stop()

# --- 核心功能函数 ---

# 用于页面显示的函数 (保持 limit=1000 以保证页面加载速度)
@st.cache_data(ttl=60)
def fetch_content_for_display(order_item_id_filter=None, search_term=None, types_filter=None):
    try:
        # 保持与原有函数名一致，但实现了新功能
        query = supabase.table("content").select("*").order("id", desc=True).limit(1000)
        
        if order_item_id_filter:
            if isinstance(order_item_id_filter, list):
                # 新增支持：如果传入的是 ID 列表，使用 in_()
                query = query.in_("order_item_id", order_item_id_filter)
            else:
                # 保持对单个 ID 的支持
                query = query.eq("order_item_id", order_item_id_filter)
                
        if search_term:
            query = query.ilike("content_text", f"%{search_term}%")
        if types_filter:
            query = query.in_("task_type", types_filter)
            
        response = query.execute()
        return response.data or []
    except Exception as e:
        st.error(f"❌ 查询内容时出错: {e}")
        return []

# ==============================================================================
# --- ✅ 新增：用于下载全部数据的函数 (无1000行限制) ---
# ==============================================================================
@st.cache_data(ttl=60) # 同样缓存结果，避免重复下载时重复请求
def fetch_all_content_for_download(order_item_id_filter=None, search_term=None, types_filter=None):
    """
    通过分页获取所有匹配的数据，绕过1000行的限制。
    """
    all_data = []
    offset = 0
    BATCH_SIZE = 1000

    while True:
        try:
            query = supabase.table("content").select("*").order("id", desc=True)
            
            # 应用与页面筛选相同的过滤条件
            if order_item_id_filter:
                query = query.eq("order_item_id", order_item_id_filter)
            if search_term:
                query = query.ilike("content_text", f"%{search_term}%")
            if types_filter:
                query = query.in_("task_type", types_filter)
            
            # 应用分页
            query = query.range(offset, offset + BATCH_SIZE - 1)
            response = query.execute()
            
            data = response.data or []
            all_data.extend(data)
            
            # 如果返回的数据量小于请求的批量大小，说明是最后一页
            if len(data) < BATCH_SIZE:
                break
            
            # 否则，准备获取下一页
            offset += BATCH_SIZE
            
        except Exception as e:
            st.error(f"❌ 下载数据时出错: {e}")
            return [] # 出错时返回空列表
            
    return all_data

# ==============================================================================
# --- ✅ 新增：用于内容分析的函数 (Task Summary & Content Count) ---
# ==============================================================================
@st.cache_data(ttl=60)
def fetch_content_analysis_data(order_item_id_list=None):
    try:
        # 1.1 获取所有任务的基本信息 (成本, 数量, 状态, 以及关联信息)
        tasks_query = supabase.table("order_items_with_status").select("*, orders!inner(*), post_type(*)")
        
        # ❗ 核心修改：应用 order_item_id 列表筛选
        if order_item_id_list is not None and order_item_id_list != []:
            tasks_query = tasks_query.in_("id", order_item_id_list)

        tasks_res = tasks_query.execute()
        tasks_df = pd.DataFrame(tasks_res.data or [])
        
        if tasks_df.empty and (order_item_id_list is not None and order_item_id_list != []):
            # 如果应用了筛选但结果为空，直接返回空 DataFrame
            return pd.DataFrame() 

        # ... (以下数据处理逻辑保持不变) ...
        
        if not tasks_df.empty:
            
            # 展平嵌套的 JSON 字段，提取所需列
            tasks_df['order_id'] = tasks_df['orders'].apply(lambda x: x.get('id') if isinstance(x, dict) else None)
            tasks_df['target_url'] = tasks_df['orders'].apply(lambda x: x.get('target_url') if isinstance(x, dict) else None)
            tasks_df['target_brand'] = tasks_df['orders'].apply(lambda x: x.get('target_brand') if isinstance(x, dict) else None)
            tasks_df['post_type_name'] = tasks_df['post_type'].apply(lambda x: x.get('post_type') if isinstance(x, dict) else None)

            # 计算总 Comment 目标和总 Quote 目标
            tasks_df['Total Comment Required'] = tasks_df['post_quantity'] * tasks_df['reply_per_post']
            tasks_df['Total Quote Required'] = tasks_df['post_quantity'] * tasks_df['quote_per_post']

            tasks_df = tasks_df[['id', 'order_id', 'target_url', 'target_brand', 'post_type_name', 
                                'post_quantity', 'Total Comment Required', 'Total Quote Required', 
                                'cost', 'content_status']].rename(
                columns={'id': 'order_item_id', 
                         'post_quantity': 'Post Required'}
            )

        # 1.2 获取所有内容的计数（分页获取）
        content_data = []
        offset = 0
        BATCH_SIZE = 1000
        while True:
            content_query = supabase.table("content").select("order_item_id, task_type")
            
            # ❗ 核心修改：应用 order_item_id 列表筛选到 content 表
            if order_item_id_list is not None and order_item_id_list != []:
                content_query = content_query.in_("order_item_id", order_item_id_list)
            
            content_query = content_query.range(offset, offset + BATCH_SIZE - 1).execute()
            
            data = content_query.data or []
            content_data.extend(data)
            if len(data) < BATCH_SIZE:
                break
            offset += BATCH_SIZE
        content_df = pd.DataFrame(content_data)

        # 2. 计算每个任务ID的内容类型计数 (保持不变)
        if not content_df.empty:
            content_counts = content_df.groupby(['order_item_id', 'task_type']).size().reset_index(name='count')
            content_pivot = content_counts.pivot(index='order_item_id', columns='task_type', values='count').fillna(0).astype(int).reset_index()
            content_pivot.rename(columns={'comment': 'Comment Generated', 'post': 'Post Generated', 'quote': 'Quote Generated', 'retweet': 'Retweet Generated'}, inplace=True)
            
            # 3. 合并数据 (逻辑保持不变)
            if not tasks_df.empty:
                merged_df = pd.merge(tasks_df, content_pivot, on='order_item_id', how='left').fillna(0)
                
                # ... (以下计算 Total Content, Total Req, Status, 格式化 cost 逻辑不变) ...
                for col in ['Post Generated', 'Comment Generated', 'Quote Generated', 'Retweet Generated']:
                    if col not in merged_df.columns:
                        merged_df[col] = 0
                    merged_df[col] = merged_df[col].astype(int)
                    
                merged_df['Total Content'] = merged_df['Post Generated'] + merged_df['Comment Generated'] + merged_df['Quote Generated'] + merged_df['Retweet Generated']
                merged_df['Total Req'] = merged_df['Post Required'] + merged_df['Total Comment Required'] + merged_df['Total Quote Required']
                
                final_cols = ['order_item_id', 'order_id', 'target_brand', 'target_url', 'post_type_name', 
                              'content_status', 'cost', 'Total Content', 'Total Req',
                              'Post Generated', 'Post Required', 
                              'Comment Generated', 'Total Comment Required', 
                              'Quote Generated', 'Total Quote Required', 'Retweet Generated']
                
                final_df = merged_df[[col for col in final_cols if col in merged_df.columns]]
                
                final_df['Status'] = final_df.apply(
                    lambda row: '✅ COMPLETE' if row['Total Content'] >= row['Total Req'] and row['content_status'] == 'DONE' else 
                                 ('⚠️ IN PROGRESS' if row['Total Content'] > 0 and row['content_status'] != 'DONE' else 
                                  '❌ EMPTY'), axis=1
                )
                
                final_df['cost'] = final_df['cost'].apply(lambda x: f'${x:.6f}')
                
                return final_df.drop(columns=['Total Req'], errors='ignore')
                
            else:
                st.warning("❌ 无法获取订单任务的基础信息 (order_items_with_status)。")
                return content_pivot.rename(columns={'order_item_id': 'Task ID'})
        
        return pd.DataFrame()
        
    except Exception as e:
        st.error(f"❌ 获取内容分析数据时出错: {e}")
        return pd.DataFrame()
    
# ==============================================================================
# --- ✅ 新增：用于图表按 URL 聚合的辅助函数 ---
# ==============================================================================
def aggregate_by_url(df: pd.DataFrame) -> pd.DataFrame:
    """
    将内容生成数据按 target_url 聚合，并汇总 Post, Comment, Quote 的生成数量。
    """
    if df.empty or 'target_url' not in df.columns:
        return pd.DataFrame()

    # 仅选择与图表相关的列，并按 URL 分组
    chart_cols = ['target_url', 'Post Generated', 'Comment Generated', 'Quote Generated', 'Retweet Generated']
    
    # 聚合：对每个 URL 求和
    aggregated_df = df[chart_cols].groupby('target_url').sum().reset_index()
    
    # 重新命名 URL 列并将其设置为索引 (Streamlit Bar Chart 默认使用索引)
    return aggregated_df.rename(columns={'target_url': 'Target URL'}).set_index('Target URL')

# --- 侧边栏过滤器 ---
with st.sidebar:
    st.header("🔎 筛选内容")
    
    # ==============================================================================
    # 1. 获取所有筛选数据源 (缓存数据)
    # ==============================================================================
    @st.cache_data(ttl=300)
    def get_all_filter_options():
        try:
            # 1. 获取所有 Project 名称
            project_res = supabase.table("projects").select("project_name").execute()
            project_names = sorted(list(set(item['project_name'] for item in project_res.data or [])))
            
            # 2. 获取所有 Target URL (替换 Brand)
            url_res = supabase.table("orders").select("target_url").execute()
            url_names = sorted(list(set(item['target_url'] for item in url_res.data or [] if item['target_url'])))
            
            # 3. 获取所有 Post Type 名称
            post_type_res = supabase.table("post_type").select("post_type").execute()
            post_type_names = sorted(list(set(item['post_type'] for item in post_type_res.data or [])))
            
            # 4. 获取所有 Task Statuses (直接使用硬编码的计算状态)
            # '✅ COMPLETE', '⚠️ IN PROGRESS', '❌ EMPTY' 是根据内容数量计算出来的，不是数据库字段
            task_statuses = ['✅ COMPLETE', '⚠️ IN PROGRESS', '❌ EMPTY'] 
            
            return project_names, url_names, post_type_names, task_statuses
        except Exception as e:
            st.error(f"❌ 获取筛选选项时出错: {e}")
            return [], [], [], []

    project_names, url_names, post_type_names, task_statuses = get_all_filter_options()

    # ==============================================================================
    # 2. 筛选器配置
    # ==============================================================================
    
    # Project 筛选 (保持不变)
    project_options = ["All Projects"] + project_names
    selected_project = st.selectbox("项目 (Project)", options=project_options)
    
    # ❗ 替换: Brand -> URL 筛选
    url_options = ["All URLs"] + url_names
    selected_url = st.selectbox("目标 URL (Target URL)", options=url_options)
    
    # Post Type 筛选 (保持不变)
    post_type_options = ["All Post Types"] + post_type_names
    selected_post_type = st.selectbox("帖子类型 (Post Type)", options=post_type_options)
    
    # ❗ 替换: Task Item ID -> Status 筛选
    status_options = ["All Statuses"] + task_statuses
    selected_status = st.selectbox("完整状态 (Status)", options=status_options)
    
    # 原始 Task Type 筛选 (post, comment, quote) (保持不变)
    selected_types = st.multiselect("内容类型 (Content Type)", options=["post", "comment", "quote", "retweet"], default=["post", "comment", "quote", "retweet"])
    
    # 原始搜索框 (保持不变)
    search_query = st.text_input("在内容中搜索关键词")

    # ==============================================================================
    # 3. 实时查询并应用新的筛选条件
    # ==============================================================================
    
    # 将选择结果存储到 session_state，供主内容区使用
    st.session_state['filter_project'] = selected_project if selected_project != "All Projects" else None
    
    # ❗ 替换 Brand 为 URL
    st.session_state['filter_url'] = selected_url if selected_url != "All URLs" else None
    
    st.session_state['filter_post_type'] = selected_post_type if selected_post_type != "All Post Types" else None
    
    # ❗ 替换 Task ID 为 Status
    st.session_state['filter_status'] = selected_status if selected_status != "All Statuses" else None
    
    st.session_state['filter_types'] = selected_types
    st.session_state['filter_search'] = search_query

    # ==============================================================================
    # --- ✅ 新增：下载功能模块 (代码保持不变) ---
    # ==============================================================================
    st.divider() # 添加一个分隔线，让界面更清晰
    st.header("📥 下载数据")

    if st.button("准备下载文件", help="点击这里，系统将根据当前筛选条件准备好完整的CSV文件供您下载。"):
        with st.spinner("正在获取所有数据，请稍候..."):
            # 1. 调用新的函数获取所有数据。注意：fetch_all_content_for_download 必须先修改以支持 Project/Brand/PostType 筛选！
            # 由于我们不知道您的表结构，我们暂时只传入 content 表已有的筛选条件。
            # 您需要确保 fetch_all_content_for_download 能够处理这些跨表筛选，
            # 或者先在 Python 中执行跨表查询，获取符合条件的 order_item_id 列表，再传入。
            
            # --- 简化的下载筛选：仅使用 content 表内的字段 ---
            all_data_to_download = fetch_all_content_for_download(
                order_item_id_filter=st.session_state['filter_task_id'],
                search_term=st.session_state['filter_search'],
                types_filter=st.session_state['filter_types']
            )
            # --- 如果要实现全筛选，需要大量修改 fetch_all_content_for_download 函数 ---
            
            if all_data_to_download:
                st.session_state['download_data'] = pd.DataFrame(all_data_to_download)
                st.session_state['download_ready'] = True
                st.success(f"✅ 准备就绪！共找到 {len(all_data_to_download)} 条数据可供下载。")
            else:
                st.warning("没有找到可供下载的数据。")
                st.session_state['download_ready'] = False

    # 如果文件已准备好，则显示下载按钮
    if st.session_state.get('download_ready', False):
        df_to_download = st.session_state['download_data']
        
        # 2. 将 DataFrame 转换为 CSV 格式 (在内存中)
        csv_buffer = io.StringIO()
        df_to_download.to_csv(csv_buffer, index=False, encoding='utf-8-sig') 
        
        # 3. 创建动态的文件名
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"content_export_{timestamp}.csv"

        # 4. 显示 Streamlit 的下载按钮
        st.download_button(
            label="点击下载 CSV 文件",
            data=csv_buffer.getvalue(),
            file_name=filename,
            mime='text/csv',
            on_click=lambda: st.session_state.update(download_ready=False)
        )


# --- 主内容显示区域：使用 Tabs ---
tab1, tab2 = st.tabs(["📋 内容详情", "📈 内容分析"])

# ==============================================================================
# --- Tab 1: 内容详情 (Content Details) ---
# ==============================================================================
with tab1:
    
    # 1. 从 session_state 中获取侧边栏的筛选条件
    selected_project = st.session_state.get('filter_project')
    selected_brand = st.session_state.get('filter_brand')
    selected_post_type = st.session_state.get('filter_post_type')
    task_id_to_filter = st.session_state.get('filter_task_id')
    search_query = st.session_state.get('filter_search')
    selected_types = st.session_state.get('filter_types')

    # 2. **核心逻辑：计算并存储最终的筛选 ID 列表**
    id_list_from_cross_filter = None
    
    # 检查是否有任何跨表筛选被选中
    if selected_project or selected_brand or selected_post_type:
        st.info("执行跨表查询以应用 Project/Brand/Post Type 筛选...")
        
        # 复杂查询: 从 order_items_with_status 表中筛选 order_item_id
        try:
            # 查询关联 orders 和 post_type 的 order_item ID
            query = supabase.table("order_items_with_status").select("id, orders!inner(project_id, target_brand), post_type!inner(post_type)")
            
            # 筛选 Project
            if selected_project:
                # 必须先查询 project_id
                project_id_res = supabase.table("projects").select("id").eq("project_name", selected_project).single().execute()
                if project_id_res.data:
                     # 筛选 orders.project_id
                     query = query.eq("orders.project_id", project_id_res.data['id'])
                else:
                    # 如果 project_id 找不到，则没有任务符合条件
                    id_list_from_cross_filter = [] 
                    st.warning(f"Project '{selected_project}' not found, showing no results.")
                    
            # 筛选 Brand
            if selected_brand:
                # 筛选 orders.target_brand
                query = query.eq("orders.target_brand", selected_brand)
                
            # 筛选 Post Type
            if selected_post_type:
                 # 筛选 post_type.post_type
                 query = query.eq("post_type.post_type", selected_post_type)

            # 只有在没有提前将 id_list_from_cross_filter 设置为 [] 时，才执行最终查询
            if id_list_from_cross_filter is None:
                cross_filter_res = query.execute()
                
                if cross_filter_res.data:
                    id_list_from_cross_filter = [item['id'] for item in cross_filter_res.data]
                else:
                    id_list_from_cross_filter = [] # 没有找到符合跨表条件的任务ID
                
        except Exception as e:
            st.error(f"❌ 跨表查询失败: {e}")
            id_list_from_cross_filter = []

    # 3. 确定最终的 order_item_id 列表 (final_task_id_filter)
    final_task_id_filter = None
    
    if task_id_to_filter:
        # 优先级最高：如果用户选择了单个 Task ID，则以它为准
        final_task_id_filter = task_id_to_filter
        
    elif id_list_from_cross_filter is not None:
        # 如果执行了跨表查询，且没有单个 Task ID 筛选
        final_task_id_filter = id_list_from_cross_filter 
        if not final_task_id_filter:
            # 如果列表为空，使用一个永远不会匹配的ID来确保结果为空
            final_task_id_filter = [-1] 

    # 4. **存储最终列表到 session_state (供 Tab 2 读取)**
    # 将最终筛选结果转换为列表形式存储，或存储 None (表示不筛选)
    if final_task_id_filter is None or final_task_id_filter == []:
        st.session_state['final_id_list'] = None
    elif isinstance(final_task_id_filter, list):
        st.session_state['final_id_list'] = final_task_id_filter
    else:
        st.session_state['final_id_list'] = [final_task_id_filter] # 单个ID转列表

    # 5. 调用 fetch_content_for_display
    content_data = fetch_content_for_display(
        order_item_id_filter=st.session_state['final_id_list'],
        search_term=search_query,
        types_filter=selected_types
    )
    
    # --- 表格展示逻辑 ---
    
    if not content_data:
        st.warning("根据当前的筛选条件，没有找到任何内容。")
    else:
        st.info(f"找到 {len(content_data)} 条匹配的内容。(页面仅显示最近的1000条)")
        
        df = pd.DataFrame(content_data)

        # --- 元数据解析逻辑 (保持不变) ---
        if 'metadata' in df.columns:
            def safe_get(data, keys, default=None):
                if not isinstance(data, dict): return default
                temp = data
                for key in keys:
                    if not isinstance(temp, dict): return default
                    temp = temp.get(key)
                return temp

            key_mappings = {
                'lang': ('l', 'language'), 'persona': ('p', 'persona'), 'style': ('s', 'style'),
                'interaction': ('it', None), 'keyword': ('k', 'keywords'), 'use_emoji': ('e', 'use_emoji'),
                'use_hashtag': ('h', 'use_hashtag'), 'use_brand': ('b', 'use_brand'),
                'used_url': ('u', 'use_url'), 'url': ('u_val', None),
            }

            for col_name, (short_key, plan_key) in key_mappings.items():
                df[col_name] = df['metadata'].apply(
                    lambda x: safe_get(x, [short_key]) if safe_get(x, [short_key]) is not None 
                              else (safe_get(x, ['plan', plan_key]) if plan_key else None)
                )

            df['keyword'] = df['keyword'].apply(lambda x: (x[0] if isinstance(x, list) and x else None))
            
            for col in ['use_emoji', 'use_hashtag', 'use_brand', 'used_url']:
                if col in df.columns:
                    df[col] = df[col].apply(lambda x: bool(x) if pd.notna(x) and x in [1, True, '1'] else False)

        # --- 表格显示 (保持不变) ---
        display_cols = [
            'id', 'task_type', 'order_item_id', 'content_text', 'lang', 'persona', 'style', 
            'interaction', 'keyword', 'used_url', 'url', 'use_emoji', 'use_hashtag', 'use_brand',
            'parent_content_id', 'created_at'
        ]
        existing_cols = [col for col in display_cols if col in df.columns]
        
        if 'created_at' in df.columns:
            df['created_at'] = pd.to_datetime(df['created_at']).dt.strftime('%Y-%m-%d %H:%M:%S')

        st.dataframe(
            df[existing_cols], width='stretch', height=1500,
            column_config={
                "content_text": st.column_config.TextColumn("Content", width="large"),
                "used_url": st.column_config.CheckboxColumn("URL?"),
                "use_emoji": st.column_config.CheckboxColumn("Emoji?"),
                "use_hashtag": st.column_config.CheckboxColumn("Hashtag?"),
                "use_brand": st.column_config.CheckboxColumn("Brand?"),
                "url": st.column_config.TextColumn("URL"),
            }
        )

# ==============================================================================
# --- Tab 2: 内容分析 (Content Analysis) ---
# ==============================================================================
with tab2:
    st.header("任务内容统计分析")
    st.caption("此表格汇总了每个任务 (Order Item ID) 所需和已生成的内容数量，以及总花费。")
    
    # ❗ 修正：直接从 session_state 读取 Tab 1 计算出的筛选 ID 列表
    # Tab 1 已经计算了最终的筛选 ID 列表并存储在 session_state 中。
    final_id_list = st.session_state.get('final_id_list', None)

    # 传入筛选列表给数据获取函数
    analysis_df = fetch_content_analysis_data(order_item_id_list=final_id_list) 
    
    if analysis_df.empty:
        st.warning("未找到任何内容统计数据。")
    else:
        
        analysis_df = analysis_df.sort_values(by='Total Content', ascending=False)
        
        # 表格配置（保持不变）
        st.dataframe(
            analysis_df, 
            hide_index=True,
            column_config={
                "order_item_id": st.column_config.NumberColumn("Task ID (Item)", format="%d"),
                "order_id": st.column_config.NumberColumn("Order ID", format="%d"), 
                "target_brand": st.column_config.TextColumn("品牌"),
                "target_url": st.column_config.TextColumn("URL"),
                "post_type_name": st.column_config.TextColumn("帖子类型"),
                "content_status": st.column_config.TextColumn("任务状态 (DB)"),
                "Status": st.column_config.TextColumn("完整状态"),
                "cost": st.column_config.TextColumn("总花费", help="该任务的总 AI 成本"),
                "Total Content": st.column_config.NumberColumn("总内容数"),
                
                "Post Required": st.column_config.NumberColumn("Post 目标"),
                "Post Generated": st.column_config.NumberColumn("Post 已生成"),
                "Total Comment Required": st.column_config.NumberColumn("**总 Comment 目标**"), 
                "Comment Generated": st.column_config.NumberColumn("Comment 已生成"),
                "Total Quote Required": st.column_config.NumberColumn("**总 Quote 目标**"), 
                "Quote Generated": st.column_config.NumberColumn("Quote 已生成"),
                "Retweet Generated": st.column_config.NumberColumn("Retweet 已生成", help="Retweet 数量"),
            },
        )

        st.markdown("---")
        st.subheader("内容类型分布图 (按 URL 汇总)")
        
        # 调用新的聚合函数，按 URL 聚合数据 (保持不变)
        chart_data_url_agg = aggregate_by_url(analysis_df)

        if not chart_data_url_agg.empty and chart_data_url_agg.sum().sum() > 0:
            st.bar_chart(chart_data_url_agg)
        else:
            st.info("数据量不足或 URL 字段为空，无法绘制按 URL 汇总的图表。")