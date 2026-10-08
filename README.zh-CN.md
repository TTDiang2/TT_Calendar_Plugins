# 🧩 TT Calendar 订阅插件

[TT Calendar](https://github.com/TTDiang2/TT_Calendar) (v2.3+) 社区插件仓库。想订阅什么日历，就装什么日历——把 `.py` 文件丢进 `plugins/`，重启即用。

> **主仓库**（应用程序本体）的官方构建包**不附带**这些插件。从这个仓库下载，放入 `plugins/` 目录，重启即可。
>
> 🇺🇸 [English README](README.md)

---

## 📦 收录插件

| 插件文件 | 数据源 | 说明 | 需要凭据 |
|---|---|---|---|
| [`investing.py`](investing.py) | 英为财情（investing.com）经济日历 | 美/中/日/欧等 16 国经济指标：时间 · 货币 · 重要性星级 · 今值/预测值/前值 · vs 预期徽标。按国家分图层展示 | ✅ Cloudflare cookie（见下文） |
| [`jisilu.py`](jisilu.py) | 集思录投资日历 | 新股 / 可转债 / 分红 / REITs / 股指期货期权等 15 类事件，按类型分图层展示 | ❌ 无需 |

## ⚙️ 安装

1. **下载插件文件**：点上面的文件名，再点页面右侧 **Download raw file**（或 `git clone` 本仓库后复制）
2. **放进 TT Calendar 的插件目录**：

   - **源码版**：`TT_Calendar/plugins/` 文件夹
   - **打包版（3 个 exe）**：在 exe 旁边新建 `plugins/` 文件夹

3. **重启应用** —— 完成。侧边栏会出现插件对应的图层分组，订阅面板可添加数据源。

> 装多个插件就把多个 `.py` 都放进去；卸载 = 删除文件。

## 📖 使用方法

### 添加订阅

1. 打开应用 → 侧边栏底部/顶栏打开 **订阅** 面板
2. 点 **+ 新增订阅**，选择已安装的插件源（如「英为财情-投资日历」），保存
3. 点该订阅卡片的 **「立即更新」**（或重启应用自动刷新）→ 事件写入对应图层

### 图层开关

侧边栏按分组显示各插件的图层，**勾选 = 显示并写入**，不勾选的图层不落库：

- `英为财情·美国 / 中国 / 日本 / 欧元区 …`（investing 按国家分 16 图层 + 「其他」兜底图层）
- `集思录·新股上市 / 可转债 / A股分红 …`（jisilu 按类型分 15 图层）

### 事件详情

点击日期 → 右侧详情面板：事件卡片会显示插件声明的字段
（如英为财情的 时间 · 货币 · 统计周期 · 重要性星级 + 今值/预测值/前值 + vs 预期徽标）——
字段展示由应用自动渲染，无需装额外前端组件。

### investing 插件：Cloudflare cookie（仅此插件需要）

英为财情被 Cloudflare 保护，普通请求会被拦截。首次使用需：

1. 用 **Edge 浏览器** 打开 https://cn.investing.com/economic-calendar ，通过人机验证
2. `F12` → Application → Cookies → 选中 `cn.investing.com`，全选复制为 JSON
3. 保存到 `data/investing_cookies.json`（应用数据目录；打包版在 exe 旁 `data/` 文件夹，没有就建一个）：

   ```json
   { "cf_clearance": "…", "__cf_bm": "…" }
   ```

4. 回应用点「立即更新」—— cookie 过期（约半天~1 天）后只需重新导出一次

## 📋 插件注册表

[`registry.json`](registry.json) 是本仓库的机器可读索引：每个插件一条，含 `source_id`、显示名、
下载地址、**sha256**、所需的 `PROTOCOL_VERSION`、凭据/网络要求、刷新窗口，以及完整的图层清单。
将来的应用内安装器就是读它。

**它是生成物，不要手改。** `tools/gen_registry.py` 会 import 每个插件，直接从 `Source`
子类的声明上读信息，因此索引不可能与代码不一致：

```bash
# 改过任何插件的声明后重新生成
python tools/gen_registry.py

# 校验索引与代码一致（CI 应跑这个）
python tools/gen_registry.py --check
```

输出刻意做成**字节稳定**（键序固定、插件按 `source_id` 排序、不含时间戳），
这样 `--check` 就是一次纯字节比对，不会产生「每次都变」的噪声 diff——那种噪声会让人
习惯性忽略失败信号。

`tests/test_registry.py` 把「索引必须与代码一致」变成会失败的断言，并校验 sha256/大小
与真实文件相符。生成器与测试都依赖 `tt_calendar` 包，需在 TT Calendar 源码树内运行
（与下面的测试同理）。

> ⚠️ **`needs_credentials` 要仔细读**：它的含义是「需要*账号*凭据」，而不是「无需任何配置」。
> `investing.py` 把它设成 `false`，但它**仍然**需要上文那份 Cloudflare cookie 文件——
> cookie 是会话绕过，不算账号认证。安装前请先看该插件的说明。

## 🧪 测试

插件测试设计为在 **TT Calendar 源码目录**下运行（依赖 `tt_calendar` 包）：

```bash
# 在 TT_Calendar 项目根目录
python -m pytest ../TT_Calendar_Plugins/tests -q
```

- `tests/test_investing_source.py`：investing 解析器单元测试（使用真实抓包样本，不发真实 HTTP 请求）

## 🤝 贡献插件

写了一个新插件？欢迎分享：

1. 先在本地 `plugins/` 目录里放好你的 `.py`（协议说明见 TT_Calendar 仓库
   [docs/SUBSCRIPTION_PLUGIN_GUIDE.md](https://github.com/TTDiang2/TT_Calendar/blob/main/docs/SUBSCRIPTION_PLUGIN_GUIDE.md)）
2. 给本仓库提 PR：插件文件放根目录，命名 `source_id.py`
3. 在上方「收录插件」表补一行，README 里说明安装与凭据要求

**协议速览**：`Source` 子类需实现 `source_id / display_name / layer_specs() / fetch(start, end)`，
可选 `field_specs()`（事件字段 UI 规格）与 `refresh_past_days / refresh_future_days`（刷新窗口）。

`LayerSpec` 的可选字段 —— **不声明则对应功能静默失效**，所以务必声明：

| 字段 | 不声明会怎样 |
|---|---|
| `sub_filter=SubFilterSpec(group_key=..., title_pattern=...)` | 按事件子动作（如【申购日】）的过滤整个失效。核心只从图层声明里读这个正则，取其中**一个**捕获组与用户在设置页勾选的子动作求交集 —— 核心不知道你的标题长什么样。 |
| `manual_pickable=False` | 该图层会出现在新建条目的点选/涂色选择器里，用户手工加的标记会被下次同步覆盖。 |

两者都存进图层行（`layer_config.config_json`），因此源被卸载后规则仍在。`ensure_layers` 只写这些键
和你自己的 `config`，**不会**动用户数据（例如已勾选的子动作）。

### 只要用到了上面这些，就必须声明 `PROTOCOL_VERSION`

```python
class MySource(Source):
    PROTOCOL_VERSION = 2   # 我需要支持协议 v2 的 app
```

加载器会拿你的值和 app 的比，**app 更旧时直接跳过你的插件并给出可读原因**，
而不是让它装上后运行到一半抛一个看不懂的 `TypeError`。
不声明版本的早期插件按 v1 处理，在更新的 app 上照常可用；
只有「插件要求高于 app」这一个方向会被拦。

---

TT Calendar 主仓库：[TTDiang2/TT_Calendar](https://github.com/TTDiang2/TT_Calendar) · 协议：MIT
