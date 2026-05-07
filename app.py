# app.py (真正最终、100%完整的版本)
import streamlit as st
from supabase import create_client
from postgrest.exceptions import APIError

# --- 页面配置 ---
st.set_page_config(
    page_title="Social Signal System",
    page_icon="🚀",
    layout="wide", # 使用 wide 布局以更好地展示项目管理
)

# --- Supabase 初始化 ---
@st.cache_resource
def init_supabase_client():
    try:
        supabase_url = st.secrets["supabase_url"]
        supabase_key = st.secrets["supabase_key"]
        return create_client(supabase_url, supabase_key)
    except Exception as e:
        st.error(f"❌ 连接数据库失败。错误: {e}")
        return None

supabase = init_supabase_client()

# --- 初始化 Session State ---
if 'user' not in st.session_state:
    st.session_state.user = None
if 'editing_project' not in st.session_state:
    st.session_state.editing_project = None

# ==============================================================================
#  登录/注册控制器
# ==============================================================================
if st.session_state.user is None:
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.title("欢迎来到 Social Signal 订单系统 👋")
        st.header("请登录或注册以继续")

        if not supabase:
            st.error("系统无法连接到数据库，请联系管理员。")
            st.stop()

        login_tab, signup_tab = st.tabs(["🔑 **登录 (Login)**", "📝 **注册 (Sign Up)**"])

        # --- 登录标签页 ---
        with login_tab:
            with st.form("login_form"):
                username = st.text_input("用户名 (Username)", key="login_username")
                password = st.text_input("密码 (Password)", type="password", key="login_password")
                login_button = st.form_submit_button("登录", width='stretch')
                
                if login_button:
                    try:
                        login_email = f"{username.lower()}@example.com"
                        user_response = supabase.auth.sign_in_with_password({
                            "email": login_email, 
                            "password": password
                        })
                        st.session_state.user = user_response.user
                        st.rerun()
                    except Exception as e:
                        st.error(f"登录失败: 用户名或密码错误。")
        
        # --- 注册标签页 ---
        with signup_tab:
            with st.form("signup_form"):
                username = st.text_input("设置用户名 (Username)", key="signup_username")
                password = st.text_input("设置密码 (Password)", type="password", key="signup_password")
                signup_button = st.form_submit_button("注册", width='stretch')

                if signup_button:
                    try:
                        fake_email = f"{username.lower()}@example.com"
                        res = supabase.auth.sign_up({
                            "email": fake_email, "password": password,
                            "options": {"data": {"username": username}}
                        })
                        if res.user:
                            st.success(f"🎉 用户 '{username}' 创建成功！请前往“登录”标签页。")
                        else:
                            st.error("注册失败，未收到用户信息。")
                    except APIError as e:
                        st.error(f"注册失败: {e.message}")
                    except Exception as e:
                        st.error(f"发生未知错误: {e}")
    st.stop()

# ==============================================================================
#  已登录用户的主应用界面
# ==============================================================================

# --- 侧边栏 ---
display_name = st.session_state.user.user_metadata.get('username', st.session_state.user.id)
st.sidebar.success(f"已登录: {display_name}")
if st.sidebar.button("🚪 登出 (Logout)"):
    st.session_state.user = None
    st.rerun()

# --- 主页面 ---
st.title("📊 项目管理中心")
st.markdown(f"您好，**{display_name}**！欢迎回来。")

# ==============================================================================
#  【已恢复】您原有的项目管理功能
# ==============================================================================
st.markdown("---")
with st.container(border=True):
    st.header("📂 创建新项目")
    st.markdown("**职责:** 此区域仅用于创建全新的项目。")

    with st.form(key="project_form", clear_on_submit=True):
        project_name = st.text_input("新项目名称 (Project Name)", help="请输入一个唯一的项目名称。")
        keywords_str = st.text_area("关键词 (Keywords)", placeholder="online casino, slot game", help="输入多个关键词，并用英文逗号 (,) 分隔。")
        submit_button = st.form_submit_button(label="💾 创建新项目")

    if submit_button:
        if not project_name or not keywords_str:
            st.warning("项目名称和关键词都不能为空。")
        else:
            keywords_to_process = list(set([kw.strip().lower() for kw in keywords_str.split(',') if kw.strip()]))
            try:
                response = supabase.table("projects").select("id").eq("project_name", project_name).maybe_single().execute()
                if response.data:
                    st.error(f"❌ 创建失败：项目 '{project_name}' 已存在。请在下方的“管理现有项目”区域进行编辑。")
                else:
                    data_to_insert = {"project_name": project_name, "keywords": keywords_to_process}
                    supabase.table("projects").insert(data_to_insert).execute()
                    st.success(f"🎉 新项目 '{project_name}' 及 {len(keywords_to_process)} 个关键词已成功创建！")
                    st.balloons()
                    st.rerun()
            except APIError as e:
                st.error(f"数据库错误: {e.message}")
            except Exception as e:
                st.error(f"发生未知错误: {e}")

# --- 管理现有项目 ---
st.markdown("---")
st.header("📈 管理现有项目")
st.markdown("**职责:** 在此区域对已存在的项目进行关键词的添加、修改和删除。")

try:
    with st.spinner("正在加载项目列表..."):
        projects_response = supabase.table("projects").select("id, project_name, keywords").order("project_name").execute()
    
    if not projects_response.data:
        st.info("数据库中还没有任何项目，请在上方表单中创建一个。")
    else:
        for project in projects_response.data:
            project_id = project['id']
            project_name = project['project_name']
            keywords = sorted(project.get('keywords', []))

            with st.expander(f"**项目: {project_name}** ({len(keywords)}个关键词)"):
                if st.session_state.editing_project != project_id:
                    st.markdown("**关键词列表:**")
                    if keywords:
                        cols = st.columns(3)
                        for i, kw in enumerate(keywords):
                            cols[i % 3].markdown(f"- `{kw}`")
                    else:
                        st.info("该项目暂无关键词。")
                    
                    if st.button("✏️ 编辑关键词", key=f"edit_{project_id}"):
                        st.session_state.editing_project = project_id
                        st.rerun()
                else:
                    st.markdown("#### 正在编辑项目: " + project_name)
                    st.markdown("取消勾选即可**删除**现有关键词。")
                    edited_keywords_status = {}
                    cols = st.columns(2)
                    for i, kw in enumerate(keywords):
                        edited_keywords_status[kw] = cols[i % 2].checkbox(kw, value=True, key=f"cb_{project_id}_{kw}")

                    st.markdown("---")
                    new_keywords_str = st.text_input("在此处**添加**新关键词 (用逗号分隔):", key=f"new_kw_{project_id}")

                    col1, col2 = st.columns([1, 1])
                    with col1:
                        if st.button("✅ 保存更改", key=f"save_{project_id}", type="primary"):
                            retained_keywords = {kw for kw, checked in edited_keywords_status.items() if checked}
                            new_keywords_set = {kw.strip().lower() for kw in new_keywords_str.split(',') if kw.strip()}
                            final_keywords = sorted(list(retained_keywords.union(new_keywords_set)))
                            
                            try:
                                supabase.table("projects").update({"keywords": final_keywords}).eq("id", project_id).execute()
                                st.success(f"项目 '{project_name}' 的关键词已成功更新！")
                                st.session_state.editing_project = None
                                st.rerun()
                            except Exception as e:
                                st.error(f"更新失败: {e}")
                    with col2:
                        if st.button("❌ 取消", key=f"cancel_{project_id}"):
                            st.session_state.editing_project = None
                            st.rerun()
except Exception as e:
    st.warning(f"加载项目列表时出错: {e}")
