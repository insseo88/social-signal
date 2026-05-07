# pages/5_Generate_Order.py
import streamlit as st
import pandas as pd
from supabase import create_client
import datetime
import random
import io
import math
import altair as alt
import numpy as np

# --- 检查登录状态 ---
if 'user' not in st.session_state or st.session_state.user is None:
    st.warning("⚠️ 请先在主页登录才能访问此页面。")
    st.page_link("app.py", label="返回主页登录", icon="🏠")
    st.stop()

# --- 页面保护和 Supabase 初始化 ---
if 'supabase' not in st.session_state:
    try:
        supabase_url = st.secrets["supabase_url"]
        supabase_key = st.secrets["supabase_key"]
        st.session_state.supabase = create_client(supabase_url, supabase_key)
    except Exception:
        st.error("无法初始化 Supabase 客户端。请检查您的 secrets 配置。")
        st.stop()

supabase = st.session_state.supabase

st.set_page_config(page_title="生成自动化订单", layout="wide")
st.title("🚀 自动化任务订单生成器")
st.markdown("从已创建的订单中选择、规划并导出用于自动化工具的任务指令。")

# ==================== [新增: Session State 初始化] ====================
if "scheduling_mode" not in st.session_state:
    st.session_state.scheduling_mode = '极限铺满'
# --- 新增这一行，防止页面刷新报错 ---
if "final_result_df" not in st.session_state:
    st.session_state.final_result_df = None
# ======================================================================

# ==================== [UI 优化] ====================
with st.sidebar:
    st.header("⚙️ 调度参数设置")

    st.subheader("活动周期")
    col1, col2 = st.columns(2)
    with col1:
        schedule_start_date = st.date_input("开始日期", value=datetime.date.today(), help="整个调度计划开始的第一天。")
    with col2:
        schedule_end_date = st.date_input("结束日期", value=datetime.date.today() + datetime.timedelta(days=26), help="整个调度计划结束的最后一天（包含当天）。")
    
    total_days = (schedule_end_date - schedule_start_date).days + 1
    if total_days > 0:
        st.metric(label="活动总天数", value=f"{total_days} 天")
    else:
        st.warning("结束日期需在开始日期之后")

    st.subheader("账号能力")
    col1, col2 = st.columns(2)
    with col1:
        posts_per_account = st.number_input("发帖/天/号", min_value=1, value=2, help="平均每个账号每天可以发布多少个主帖。")
    with col2:
        engages_per_account = st.number_input("互动/天/号", min_value=1, value=6, help="平均每个账号每天可以完成多少次互动。")
    total_accounts = st.number_input("共享账号池总数", min_value=1, value=300, help="整个自动化系统可用的账号总数量。")

    st.subheader("调度策略")
    # 1. 移除模式选择，改为固定的“尽速分配”说明
    st.info("💡 **当前模式：尽速分配**\n任务将根据账号日发布能力尽快分发，确保任务不积压。")

    with st.expander("⚙️ 互动发布约束", expanded=True):
        # 2. 总互动周期说明 (根据逻辑自动计算 3, 5, 7天)
        st.markdown("""
        **互动周期逻辑：**
        - 系统将根据任务执行进度，自动将周期归类为 **3天、5天、7天**。
        """)
        
        # 3. 互动的delay（MIN)部分修改：默认3小时内
        # 我们设定最小延迟5分钟，最大180分钟（3小时）
        st.write("🕒 **互动时间窗：** 主帖发布后 **3小时内** 开始。")
        
        post_delay_min = st.number_input(
            "互动最小延迟 (分钟)", 
            min_value=1, 
            max_value=30, 
            value=5, 
            help="互动任务相对于主帖发布时间的最早开始时间。"
        )
        
        # 定义最大延迟 (3小时即180分钟)
        post_delay_max = st.number_input(
            "互动最大延迟 (分钟)", 
            min_value=60, 
            max_value=180, 
            value=180, 
            help="互动任务相对于主帖发布时间的最晚开始时间。"
        )
        
        # 保留原有的窗口设置
        post_finish_window = st.number_input("主帖完成窗口 (分钟)", min_value=1, value=10, help="主帖任务的执行时间窗口。")
        engagement_finish_window = st.number_input("单个互动完成窗口 (分钟)", min_value=1, value=2, help="互动任务的执行时间窗口。")

    # 注意：为了兼容后续逻辑，如果代码后面有用到 st.session_state.scheduling_mode 或 force_same_day，
    # 我们在这里进行静默初始化，避免程序报错。
    st.session_state['scheduling_mode'] = '极限铺满' 
    force_same_day = False
# =======================================================

# --- 数据获取函数 (带缓存) ---
@st.cache_data(ttl=300)
def get_projects():
    try:
        return supabase.table("projects").select("id, project_name").execute().data or []
    except Exception as e:
        st.error(f"获取项目列表失败: {e}")
        return []

@st.cache_data(ttl=60)
def get_orders_for_selection(project_ids, start_date, end_date, retool_statuses):
    try:
        query = supabase.table("order_items_with_status").select(
            "id, content_status, "
            "orders!inner("
                "id, target_brand, target_url, start_date, "
                "project:project_id(project_name), "
                "website:target_url(display_name:target_url)" # 👈 关键修改：从 website_name 表取 target_url 列并命名为 display_name
            "), "
            "post_type(post_type), "
            "post_quantity, reply_per_post, quote_per_post, retweet_per_post, "
            "status_view:order_item_retool_status!fk_content_order!left(retool_status)"
        )
        if project_ids:
            query = query.in_("orders.project_id", project_ids)
        if start_date:
            query = query.gte("orders.start_date", str(start_date))
        if end_date:
            query = query.lte("orders.start_date", str(end_date))
        
        orders = query.execute().data or []
        
        clean_orders = []
        for item in orders:
            order_details = item.get('orders', {})

            # 优先尝试获取关联表的 website_name，如果没有则退回到 target_url
            website_info = order_details.get('website')
            if isinstance(website_info, dict):
                # 这里使用上面定义的别名 display_name
                display_url = website_info.get('display_name', order_details.get('target_url', 'N/A'))
            else:
                display_url = order_details.get('target_url', 'N/A')

            status_data = item.get('status_view')
            retool_status = 'PENDING'
            if isinstance(status_data, list) and status_data:
                retool_status = status_data[0].get('retool_status', 'PENDING')
            elif isinstance(status_data, dict):
                retool_status = status_data.get('retool_status', 'PENDING')
            
            if retool_statuses and retool_status not in retool_statuses:
                continue

            clean_orders.append({
                "order_item_id": item['id'],
                "project": order_details.get('project', {}).get('project_name', 'N/A'),
                "brand": order_details.get('target_brand', 'N/A'),
                "url": display_url, # 👈 此时这里存的就是 website_name 表里的名称了
                "post_type": item.get('post_type', {}).get('post_type', 'N/A'),
                "content_status": item.get('content_status', 'PENDING'),
                "retool_status": retool_status,
                "posts": item.get('post_quantity', 0),
                "comments": item.get('reply_per_post', 0) * item.get('post_quantity', 0),
                "quotes": item.get('quote_per_post', 0) * item.get('post_quantity', 0),
                "retweets": item.get('retweet_per_post', 0) * item.get('post_quantity', 0),
            })
        return clean_orders
    except Exception as e:
        st.error(f"获取订单列表失败: {e}")
        return []
    
@st.cache_data(ttl=60)
def get_all_content_for_order_items(order_item_ids: list):
    if not order_item_ids:
        return [], {}
    all_content = []
    offset = 0
    BATCH_SIZE = 1000
    while True:
        try:
            response = supabase.table("content_retool").select(
                "id, order_item_id, task_type, content_text, retool_task_id, parent_content_id"
            ).in_("order_item_id", order_item_ids).range(offset, offset + BATCH_SIZE - 1).execute()
            data = response.data or []
            all_content.extend(data)
            if len(data) < BATCH_SIZE:
                break
            offset += len(data)
        except Exception as e:
            st.error(f"分页获取内容时出错: {e}")
            return [], {}
    posts = [c for c in all_content if c.get('task_type') == 'post']
    engagements = [c for c in all_content if c.get('task_type') in ['comment', 'quote', 'retweet'] and c.get('parent_content_id') is not None]
    engagement_map = {p['id']: [] for p in posts}
    for eng in engagements:
        if eng['parent_content_id'] in engagement_map:
            engagement_map[eng['parent_content_id']].append(eng)
    return posts, engagement_map

# --- 1. 订单筛选 ---
st.header("1. 订单筛选与选择")
projects = get_projects()
project_options = {p['id']: p['project_name'] for p in projects}

col1, col2, col3, col4 = st.columns(4)
with col1:
    selected_project_ids = st.multiselect("选择项目", options=project_options.keys(), format_func=lambda x: project_options[x])
with col2:
    filter_start_date = st.date_input("订单开始日期 (From)", value=None)
with col3:
    filter_end_date = st.date_input("订单结束日期 (To)", value=None)
with col4:
    selected_retool_statuses = st.multiselect("Retool 状态", options=["PENDING", "DONE"], default=["PENDING"])

orders_to_display = get_orders_for_selection(selected_project_ids, filter_start_date, filter_end_date, selected_retool_statuses)

if not orders_to_display:
    st.info("根据当前筛选条件，未找到任何订单。")
else:
    df_orders = pd.DataFrame(orders_to_display)
    df_orders['select'] = False
    st.write(f"找到 {len(df_orders)} 个符合条件的订单任务。请勾选需要调度的任务：")
    edited_df = st.data_editor(
        df_orders,
        column_config={
            "select": st.column_config.CheckboxColumn("选择", default=False),
            "project": "项目", 
            "brand": "品牌", 
            "url": "目标网站", # 👈 这里建议改为“目标网站”或“Website Name”
            "post_type": "帖子类型",
            "content_status": "内容状态",
            "retool_status": "Retool状态",
            "posts": "主帖",
            "comments": "评论",
            "quotes": "引用",
            "retweets": "转推"
        },
        column_order=["select", "content_status", "retool_status", "project", "brand", "url", "post_type", "posts", "comments", "quotes", "retweets"],
        disabled=["project", "brand", "url", "post_type", "content_status", "retool_status", "posts", "comments", "quotes", "retweets"],
        hide_index=True, key="order_selector"
    )
    selected_orders_df = edited_df[edited_df.select]
    
    if not selected_orders_df.empty:
        st.header("2. 任务汇总与约束分析")
        total_posts_selected = selected_orders_df['posts'].sum()
        total_engagements_selected = selected_orders_df['comments'].sum() + selected_orders_df['quotes'].sum() + selected_orders_df['retweets'].sum()
        col1, col2 = st.columns(2)
        col1.metric("已选主帖总数", f"{total_posts_selected:,}")
        col2.metric("已选互动总数", f"{total_engagements_selected:,}")

        if total_days <= 0:
            st.stop()
        
        url_summary = selected_orders_df.groupby('url').agg(
            total_posts=('posts', 'sum'),
            total_engagements=('comments', lambda x: selected_orders_df.loc[x.index, ['comments', 'quotes', 'retweets']].sum(axis=1).sum())
        ).reset_index()
        
        st.subheader("账号分配与能力分析")

        df = url_summary.copy()
        df['daily_req_posts'] = df['total_posts'] / total_days
        df['daily_req_engages'] = df['total_engagements'] / total_days
        
        needed_post_acc = (df['daily_req_posts'] / posts_per_account).apply(np.ceil)
        needed_eng_acc = (df['daily_req_engages'] / engages_per_account).apply(np.ceil)
        
        total_needed_acc = needed_post_acc.sum() + needed_eng_acc.sum()
        
        if total_needed_acc > 0:
            df['Allocated_PostAcc'] = (total_accounts * needed_post_acc / total_needed_acc).round().astype(int)
            df['Allocated_EngAcc'] = (total_accounts * needed_eng_acc / total_needed_acc).round().astype(int)
        else:
            df['Allocated_PostAcc'] = 0
            df['Allocated_EngAcc'] = 0

        df['Achievable_Posts_per_Day'] = df['Allocated_PostAcc'] * posts_per_account
        df['Achievable_Engage_per_Day'] = df['Allocated_EngAcc'] * engages_per_account
        df['Total_Posts'] = df['Achievable_Posts_per_Day'] * total_days
        df['Total_Engagements'] = df['Achievable_Engage_per_Day'] * total_days
        df['PostAcc_Deficit'] = (needed_post_acc - df['Allocated_PostAcc']).clip(lower=0).astype(int)
        df['EngAcc_Deficit'] = (needed_eng_acc - df['Allocated_EngAcc']).clip(lower=0).astype(int)
        
        st.session_state.analysis_df = df.copy()

        total_row = df.select_dtypes(include=np.number).sum().to_frame().T
        total_row['url'] = 'TOTAL'
        
        display_df = pd.concat([df, total_row], ignore_index=True)

        st.dataframe(
            display_df,
            column_config={
                "url": st.column_config.TextColumn("品牌"),
                "daily_req_posts": st.column_config.NumberColumn("日均目标 (主帖)", format="%.1f"),
                "daily_req_engages": st.column_config.NumberColumn("日均目标 (互动)", format="%.1f"),
                "Allocated_PostAcc": st.column_config.NumberColumn("已分配 (发帖号)", format="%d"),
                "Allocated_EngAcc": st.column_config.NumberColumn("已分配 (互动号)", format="%d"),
                "Achievable_Posts_per_Day": st.column_config.NumberColumn("每日可发 (主帖)", format="%.1f"),
                "Achievable_Engage_per_Day": st.column_config.NumberColumn("每日可做 (互动)", format="%.1f"),
                "Total_Posts": st.column_config.NumberColumn("周期总发帖量", format="%.0f"),
                "Total_Engagements": st.column_config.NumberColumn("周期总互动量", format="%.0f"),
                "PostAcc_Deficit": st.column_config.NumberColumn("发帖号赤字", format="%d"),
                "EngAcc_Deficit": st.column_config.NumberColumn("互动号赤字", format="%d"),
                "total_posts": None, "total_engagements": None,
            },
            column_order=[
                "url", "daily_req_posts", "daily_req_engages", 
                "Allocated_PostAcc", "Allocated_EngAcc",
                "Achievable_Posts_per_Day", "Achievable_Engage_per_Day",
                "Total_Posts", "Total_Engagements",
                "PostAcc_Deficit", "EngAcc_Deficit"
            ],
            hide_index=True,
            use_container_width=True
        )

# --- 3. 生成并导出 ---
st.header("3. 生成并导出调度计划")

def get_engagement_cycle_range(hours_diff: float) -> str:
    if pd.isna(hours_diff): return 'N/A'
    days_diff = hours_diff / 24
    if days_diff <= 3.1: return "3 days"
    if days_diff <= 5.1: return "5 days"
    if days_diff <= 7.1: return "7 days"
    # 如果超过7天，如实显示天数，方便排查堆积
    return f"{math.ceil(days_diff)} days"

is_ready_to_generate = ('selected_orders_df' in locals() and not selected_orders_df.empty) and \
                       ('analysis_df' in st.session_state and not st.session_state.analysis_df.empty)

if st.button("🚀 生成自动化调度计划", type="primary", disabled=not is_ready_to_generate):
    with st.spinner(f"正在应用“{st.session_state.scheduling_mode}”策略生成调度..."):
        # --- 1. [修正] 数据准备：先对选择的订单项进行物理去重 ---
        # 确保每个 order_item_id 只出现一次，防止后续 merge 爆炸
        deduped_selected_orders = selected_orders_df.drop_duplicates(subset=['order_item_id'])
        selected_order_item_ids = deduped_selected_orders['order_item_id'].tolist()
        
        # 抓取内容
        all_posts, raw_engagement_map = get_all_content_for_order_items(selected_order_item_ids)
        
        if not all_posts:
            st.error("❌ 操作失败: 您选择的任务中不包含任何已生成的主帖内容。"); st.stop()

        # --- 2. [修正] 内容物理去重：确保同一个数据库 ID 只处理一次 ---
        posts_df = pd.DataFrame(all_posts).drop_duplicates(subset=['id'])
        
        # 互动任务去重：防止同一个互动任务被反复加入队列
        engagement_map = {}
        for p_id, eng_list in raw_engagement_map.items():
            if eng_list:
                # 关键：根据互动任务的数据库 ID 去重
                unique_engs = pd.DataFrame(eng_list).drop_duplicates(subset=['id']).to_dict('records')
                engagement_map[p_id] = unique_engs
            else:
                engagement_map[p_id] = []

        # 映射 URL
        order_info_df = deduped_selected_orders[['order_item_id', 'url']].rename(columns={'order_item_id': 'order_item_id_ref'})
        posts_for_scheduling_df = pd.merge(posts_df, order_info_df, left_on='order_item_id', right_on='order_item_id_ref', how='left')

        # 再次清理空格，防止匹配失效导致主帖“失踪”
        posts_for_scheduling_df['url'] = posts_for_scheduling_df['url'].astype(str).str.strip()
        all_urls_in_orders = [u for u in posts_for_scheduling_df['url'].unique() if u and u != 'nan']

        # 初始化分析容器
        site_targets = {}
        for _, row in st.session_state.analysis_df.iterrows():
            site_targets[str(row['url']).strip()] = {
                'post_capacity': row['Achievable_Posts_per_Day'],
                'eng_capacity': row['Achievable_Engage_per_Day'],
            }

        # --- 3. 开始各网站循环 (全速贪婪模式：填满前期 Quota) ---
        final_schedule_list = []
        analysis_counts_all_sites = {}
        scheduling_failed_sites = []
        
        schedule_period = [schedule_start_date + datetime.timedelta(days=i) for i in range(total_days)]

        for url in all_urls_in_orders:
            st.info(f"正在处理网站 '{url}'...")
            url_target_info = site_targets.get(url)
            if not url_target_info:
                scheduling_failed_sites.append(url); continue

            posts_queue = posts_for_scheduling_df[posts_for_scheduling_df['url'] == url].to_dict('records')
            # 互动最多的先发，产生海量需求供前期填补
            posts_queue.sort(key=lambda p: len(engagement_map.get(p['id'], [])), reverse=True)
            
            engagements_queue = []
            site_daily_counts = {day: {'posts': 0, 'engagements': 0} for day in schedule_period}
            physical_eng_cap = math.ceil(url_target_info.get('eng_capacity', 0)) # 1458
            physical_post_cap = math.ceil(url_target_info.get('post_capacity', 0))

            for i, day in enumerate(schedule_period):
                # --- A. 主帖调度 (全速：每天顶满 Capacity) ---
                posts_scheduled_today = 0
                while posts_scheduled_today < physical_post_cap and posts_queue:
                    post = posts_queue.pop(0)
                    post['schedule_datetime'] = datetime.datetime.combine(day, datetime.time(random.randint(6, 11), random.randint(0, 59)))
                    
                    final_schedule_list.append({
                        'id': post['id'], 'task_id': post['retool_task_id'], 'content_text': post['content_text'], 
                        'group_id': post['id'], 'schedule_datetime': post['schedule_datetime'], 
                        'url': url, 'actual_schedule_time': None, 'task_type': 'post'
                    })
                    site_daily_counts[day]['posts'] += 1
                    posts_scheduled_today += 1
                    
                    # --- B. 滴灌分配 (极大压缩：3-6天内全部释放) ---
                    engs = engagement_map.get(post['id'], [])
                    for idx, eng in enumerate(engs):
                        if idx < 3:
                            # 种子任务：0-1天内解禁 (最高优先级，确保极速开始)
                            available_from = day + datetime.timedelta(days=random.randint(0, 1))
                            prio = 0
                        else:
                            # 剩余任务：随机 2-6 天解禁 (压缩长尾)
                            available_from = day + datetime.timedelta(days=random.randint(2, 6))
                            prio = 1
                            
                        engagements_queue.append({
                            'engagement': eng, 'post': post,
                            'available_from': available_from, 'priority': prio
                        })
                
                # --- C. 互动调度 (强力抢占逻辑) ---
                daily_quota_left = physical_eng_cap # 1458
                
                # 提取已解禁
                ready_tasks = [item for item in engagements_queue if item['available_from'] <= day]
                future_tasks = [item for item in engagements_queue if item['available_from'] > day]
                
                # 排序：急件优先
                ready_tasks.sort(key=lambda x: (x['priority'], x['available_from']))
                
                # 执行已到期
                to_process_today = ready_tasks[:daily_quota_left]
                remaining_ready = ready_tasks[daily_quota_left:]
                daily_quota_left -= len(to_process_today)
                
                # [核心补位]：如果 1458 还没满，不计代价抓取未来任务
                if daily_quota_left > 0 and future_tasks:
                    # 不管 available_from 是哪天，只要主帖发了，全部抓回来填坑
                    future_tasks.sort(key=lambda x: (x['available_from'], x['priority']))
                    backfill = future_tasks[:daily_quota_left]
                    future_tasks = future_tasks[daily_quota_left:]
                    to_process_today.extend(backfill)
                    daily_quota_left -= len(backfill)

                # 生成时间
                for item in to_process_today:
                    post_dt = item['post']['schedule_datetime']
                    if post_dt.date() == day:
                        exec_time = post_dt + datetime.timedelta(minutes=random.randint(45, 240))
                    else:
                        exec_time = datetime.datetime.combine(day, datetime.time(random.randint(8, 22), random.randint(0, 59)))

                    final_schedule_list.append({
                        'id': item['engagement']['id'], 'task_id': item['engagement']['retool_task_id'], 
                        'content_text': item['engagement']['content_text'], 'group_id': item['post']['id'], 
                        'schedule_datetime': None, 'url': url, 'actual_schedule_time': exec_time, 
                        'task_type': 'engagement'
                    })
                    site_daily_counts[day]['engagements'] += 1
                
                engagements_queue = remaining_ready + future_tasks

            # 收尾剩余积压
            if engagements_queue:
                last_day = schedule_period[-1]
                for item in engagements_queue:
                    final_schedule_list.append({
                        'id': item['engagement']['id'], 'task_id': item['engagement']['retool_task_id'],
                        'content_text': item['engagement']['content_text'], 'group_id': item['post']['id'],
                        'schedule_datetime': None, 'url': url,
                        'actual_schedule_time': datetime.datetime.combine(last_day, datetime.time(23, 59)),
                        'task_type': 'engagement'
                    })
                    site_daily_counts[last_day]['engagements'] += 1
                    if url not in scheduling_failed_sites: scheduling_failed_sites.append(url)
            
            analysis_counts_all_sites[url] = site_daily_counts

        # ==================== [4. 数据后处理 - 恢复 command 列与 output_df] ====================
        st.info("正在进行数据格式化与指令构建...")
        if not final_schedule_list:
            st.error("❌ 调度失败。"); st.stop()
        
        result_df = pd.DataFrame(final_schedule_list)
        result_df['schedule_datetime'] = pd.to_datetime(result_df['schedule_datetime'])
        result_df['actual_schedule_time'] = pd.to_datetime(result_df['actual_schedule_time'])

        # 映射发布基准时间
        post_times = result_df[result_df['task_type'] == 'post'].drop_duplicates('group_id').set_index('group_id')['schedule_datetime']
        result_df['base_time'] = result_df['group_id'].map(post_times)
        
        # 计算 delay 和 command
        result_df['delay(MIN)'] = result_df.apply(lambda r: round((r['actual_schedule_time'] - r['base_time']).total_seconds() / 60) if r['task_type'] == 'engagement' else 0, axis=1)
        result_df['task finish between(MIN)'] = result_df['task_type'].apply(lambda t: post_finish_window if t == 'post' else engagement_finish_window)
        result_df['command'] = result_df.apply(lambda r: f"{r['task_id']}|1|{r['delay(MIN)']}|{r['task finish between(MIN)']}|{str(r.get('content_text', '')).replace('|', '/')}", axis=1)
        
        # 计算总周期
        last_eng_ts = result_df.groupby('group_id')['actual_schedule_time'].max()
        hours_diff = (last_eng_ts - post_times).dt.total_seconds() / 3600
        result_df['total_cycle'] = result_df['group_id'].map(hours_diff.apply(get_engagement_cycle_range)).fillna('N/A')

        # --- 新增：将 task_type 映射为易读的 Post 和 Eng ---
        result_df['Category'] = result_df['task_type'].map({'post': 'Post', 'engagement': 'Eng'})

        # [统一命名] 定义 output_df，在筛选列里增加 'Category'
        output_df = result_df.sort_values(by=['url', 'group_id', 'delay(MIN)'])[[
            'id', 'command', 'group_id', 'url', 'base_time', 'actual_schedule_time', 'total_cycle', 'Category'
        ]].rename(columns={'base_time': 'schedule_datetime'})
        
        st.session_state.final_result_df = output_df
        st.success(f"✅ 调度成功！共生成 {len(output_df)} 条指令。")

        # ==================== [5. 健全性检查与可视化图表] ====================
        with st.expander("📊 查看调度分析与健全性检查", expanded=True):
            st.markdown("#### 1. 每日发布量检查")
            for url_name in all_urls_in_orders:
                st.write(f"**网站: {url_name}**")
                daily_counts_data = analysis_counts_all_sites.get(url_name, {})
                analysis_data = []
                
                target_info = site_targets.get(url_name, {})
                p_cap = math.ceil(target_info.get('post_capacity', 1))
                e_cap = math.ceil(target_info.get('eng_capacity', 1))

                for day in schedule_period:
                    c = daily_counts_data.get(day, {'posts': 0, 'engagements': 0})
                    analysis_data.append({"Date": day, "Posts": c['posts'], "Post Capacity": p_cap, "Engagements": c['engagements'], "Eng. Capacity": e_cap})

                url_plot_df = pd.DataFrame(analysis_data)
                
                # 绘制每日负荷图
                base_chart = alt.Chart(url_plot_df).encode(x=alt.X('Date:T', title='日期'))
                
                # 主帖线
                p_line = base_chart.mark_line(color='#FF4B4B', point=True).encode(y=alt.Y('Posts:Q', title='主帖量'))
                p_rule = base_chart.mark_rule(color='#FF4B4B', strokeDash=[5,5]).encode(y='Post Capacity:Q')
                
                # 互动线
                e_line = base_chart.mark_line(color='#0068C9', point=True).encode(y=alt.Y('Engagements:Q', title='互动量'))
                e_rule = base_chart.mark_rule(color='#0068C9', strokeDash=[5,5]).encode(y='Eng. Capacity:Q')

                st.altair_chart(alt.layer(p_line + p_rule, e_line + e_rule).resolve_scale(y='independent'), use_container_width=True)

            st.markdown("#### 2. 完成时间检查")
            last_task_time = output_df['actual_schedule_time'].max()
            if pd.isna(last_task_time): last_task_time = output_df['schedule_datetime'].max()

            if not pd.isna(last_task_time):
                st.write(f"最后一个任务预计执行时间: **{last_task_time.strftime('%Y-%m-%d %H:%M')}**")
                if last_task_time.date() > schedule_end_date:
                    st.error(f"🚨 警告：已超出活动结束日期 ({schedule_end_date})！")
                else:
                    st.success(f"✅ 合规：在活动期限内完成。")
        
        st.subheader("最终调度结果")
        # 这里的 drop 去掉 id，保留 Category 进行显示
        st.dataframe(output_df.drop(columns=['id']), hide_index=True, column_config={
            "Category": "类型", # 新增这一行
            "command": "Command", 
            "group_id": "帖子组ID", 
            "url": "网站", 
            "schedule_datetime": st.column_config.DatetimeColumn("基准时间(主帖)", format="YYYY-MM-DD HH:mm"), 
            "actual_schedule_time": st.column_config.DatetimeColumn("实际时间(互动)", format="YYYY-MM-DD HH:mm"), 
            "total_cycle": "总互动周期"
        })
        st.session_state.final_result_df = output_df

st.divider()
st.subheader("📊 调度逻辑深度分析 (带占比统计)")

if st.session_state.get('final_result_df') is not None and not st.session_state.final_result_df.empty:
    df_ana = st.session_state.final_result_df.copy()
    df_ana['schedule_datetime'] = pd.to_datetime(df_ana['schedule_datetime'])
    df_ana['actual_schedule_time'] = pd.to_datetime(df_ana['actual_schedule_time'])
    
    # 提取去重后的主帖组数据
    posts_base = df_ana.sort_values('schedule_datetime').drop_duplicates('group_id')
    engs_only = df_ana[df_ana['actual_schedule_time'].notna()]
    
    if not engs_only.empty:
        # 1. 计算核心指标
        first_eng = engs_only.groupby('group_id')['actual_schedule_time'].min()
        last_eng = engs_only.groupby('group_id')['actual_schedule_time'].max()
        
        metrics_df = pd.DataFrame({'post_time': posts_base.set_index('group_id')['schedule_datetime']}).join(
            pd.DataFrame({'first_eng_time': first_eng, 'last_eng_time': last_eng}),
            how='inner'
        ).dropna()

        metrics_df['start_gap_hrs'] = (metrics_df['first_eng_time'] - metrics_df['post_time']).dt.total_seconds() / 3600
        metrics_df['total_cycle_days'] = (metrics_df['last_eng_time'] - metrics_df['post_time']).dt.total_seconds() / 86400
        total_groups = len(metrics_df)

        # --- 2. 布局图表 ---
        col_chart1, col_chart2 = st.columns(2)

        with col_chart1:
            st.write("📌 **互动周期分布 (按天数排序)**")
            
            # 准备周期数据并计算百分比
            cycle_counts = df_ana.drop_duplicates('group_id')['total_cycle'].value_counts().reset_index()
            cycle_counts.columns = ['total_cycle', 'count']
            cycle_counts['percent'] = (cycle_counts['count'] / cycle_counts['count'].sum() * 100).round(1)
            cycle_counts['label'] = cycle_counts['percent'].astype(str) + '%'
            
            # 提取数字进行排序（解决 10 days 排在 3 days 前面的问题）
            cycle_counts['sort_val'] = pd.to_numeric(
                cycle_counts['total_cycle'].str.extract('(\d+)', expand=False), 
                errors='coerce'
            ).fillna(0).astype(int)
            
            cycle_counts = cycle_counts.sort_values('sort_val')
            sorted_order = cycle_counts['total_cycle'].tolist()

            # 绘图
            base = alt.Chart(cycle_counts).encode(
                x=alt.X('total_cycle:N', sort=sorted_order, title='周期类型'),
                y=alt.Y('count:Q', title='帖子组数量')
            )
            bars = base.mark_bar(size=40, cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                color=alt.Color('total_cycle:N', scale=alt.Scale(scheme='blues'), legend=None),
                tooltip=['total_cycle', 'count', 'label']
            )
            text = base.mark_text(align='center', baseline='bottom', dy=-5).encode(text='label:N')
            
            st.altair_chart((bars + text).properties(height=350), use_container_width=True)

        with col_chart2:
            st.write("⏳ **首个互动延迟占比 (Gap %)**")
            
            # --- 修正后的延迟区间 (单位: 小时) ---
            # 边界: 0, 1(1h), 24(1d), 72(3d), 120(5d), 168(7d), 240(10d), 99999(极大值)
            # 共有 8 个边界，对应 7 个标签
            bins = [0, 1, 24, 72, 120, 168, 240, 99999]
            labels = ['<1h', '1-24h', '1-3天', '3-5天', '5-7天', '7-10天', '>10天']
            
            # 使用 pd.cut 进行分段
            metrics_df['gap_range'] = pd.cut(
                metrics_df['start_gap_hrs'], 
                bins=bins, 
                labels=labels, 
                right=False
            )
            
            # 统计并计算百分比
            gap_stats = metrics_df['gap_range'].value_counts().reset_index()
            gap_stats.columns = ['gap_range', 'count']
            gap_stats['percent'] = (gap_stats['count'] / total_groups * 100).round(1)
            gap_stats['label'] = gap_stats['percent'].astype(str) + '%'

            # 绘图逻辑：保持 labels 定义的顺序
            base_gap = alt.Chart(gap_stats).encode(
                x=alt.X('gap_range:N', sort=labels, title='主帖发布后多久开始互动'),
                y=alt.Y('count:Q', title='帖子组数量')
            )
            
            # 柱状图 + 百分比文字
            bars_gap = base_gap.mark_bar(size=35, color="#FFAA00").encode(
                tooltip=['gap_range', 'count', 'label']
            )
            
            text_gap = base_gap.mark_text(
                align='center', 
                baseline='bottom', 
                dy=-5,
                fontWeight='bold'
            ).encode(text='label:N')
            
            st.altair_chart((bars_gap + text_gap).properties(height=350), use_container_width=True)   

st.divider()
# --- 4. 保存与下载 ---
if st.session_state.get('final_result_df') is not None and not st.session_state.final_result_df.empty:
    st.header("4. 保存与下载")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("💾 保存计划到数据库", type="primary"):
            with st.spinner("正在将调度指令更新到 Supabase..."):
                df_to_update = st.session_state.final_result_df
                
                updates = []
                for _, row in df_to_update.iterrows():
                    update_payload = {'id': row['id'], 'retool_command': row['command']}
                    # 统一使用 retool_datetime 字段
                    task_time = row['actual_schedule_time'] if pd.notna(row['actual_schedule_time']) else row['schedule_datetime']
                    if pd.notna(task_time):
                        update_payload['retool_datetime'] = task_time.isoformat()
                    updates.append(update_payload)
                
                try:
                    # 确保表名是 content
                    supabase.table('content').upsert(updates, on_conflict='id').execute()
                    st.success("✅ 成功！所有调度指令已保存到数据库。")
                    st.cache_data.clear()
                except Exception as e:
                    st.error(f"❌ 保存到数据库失败: {e}")

    with col2:
        try:
            output_excel = io.BytesIO()
            df_to_download = st.session_state.final_result_df.drop(columns=['id']).copy()
            
            # 确保在转换格式前，列是 datetime 类型
            df_to_download['schedule_datetime'] = pd.to_datetime(df_to_download['schedule_datetime'])
            df_to_download['actual_schedule_time'] = pd.to_datetime(df_to_download['actual_schedule_time'])

            # 安全地格式化，NaT（Not a Time）值会变成空字符串
            df_to_download['schedule_datetime'] = df_to_download['schedule_datetime'].dt.strftime('%Y-%m-%d %H:%M:%S').replace('NaT', '')
            df_to_download['actual_schedule_time'] = df_to_download['actual_schedule_time'].dt.strftime('%Y-%m-%d %H:%M:%S').replace('NaT', '')

            with pd.ExcelWriter(output_excel, engine='xlsxwriter') as writer:
                df_to_download.to_excel(writer, index=False, sheet_name='Schedule')
            
            # 确保在显示下载按钮之前，output_excel 已经被填充
            excel_data = output_excel.getvalue()

            st.download_button(
                label="📥 下载调度计划 (Excel)",
                data=excel_data,
                file_name=f"automation_schedule_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            st.error(f"下载 Excel 文件时出错: {e}")